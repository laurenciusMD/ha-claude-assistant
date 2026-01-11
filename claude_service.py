#!/usr/bin/env python3
"""
Claude Assistant Service for Home Assistant
Uses Claude Code CLI to provide AI assistance with image analysis
"""

import os
import sys
import json
import asyncio
import logging
import subprocess
from aiohttp import web, ClientSession
from pathlib import Path
import base64

# Configuration from environment
API_KEY = os.getenv('ANTHROPIC_API_KEY', '')
LOG_LEVEL = os.getenv('LOG_LEVEL', 'info').upper()
ENABLE_IMAGE_ANALYSIS = os.getenv('ENABLE_IMAGE_ANALYSIS', 'true').lower() == 'true'
SUPERVISOR_TOKEN = os.getenv('SUPERVISOR_TOKEN', '')
HA_URL = os.getenv('HOMEASSISTANT_URL', 'http://supervisor/core')

# Setup logging
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('claude_assistant')

class ClaudeService:
    """Main service class for Claude Assistant"""
    
    def __init__(self):
        self.ha_session = None
        self.app = web.Application()
        self.setup_routes()
        
    def setup_routes(self):
        """Setup HTTP routes"""
        self.app.router.add_post('/api/chat', self.handle_chat)
        self.app.router.add_post('/api/analyze_image', self.handle_analyze_image)
        self.app.router.add_post('/api/analyze_snapshot', self.handle_analyze_snapshot)
        self.app.router.add_get('/api/health', self.handle_health)
        
    async def start(self):
        """Start the service"""
        logger.info("Starting Claude Assistant Service")
        
        # Create HTTP session for HA communication
        self.ha_session = ClientSession(headers={
            'Authorization': f'Bearer {SUPERVISOR_TOKEN}',
            'Content-Type': 'application/json'
        })
        
        # Register services in Home Assistant
        await self.register_ha_services()
        
        # Start web server
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', 8099)
        await site.start()
        
        logger.info("Claude Assistant Service started on port 8099")
        
        # Keep running
        try:
            await asyncio.Event().wait()
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            if self.ha_session:
                await self.ha_session.close()
    
    async def register_ha_services(self):
        """Register services in Home Assistant"""
        logger.info("Registering Home Assistant services...")
        
        services = [
            {
                'domain': 'claude',
                'service': 'chat',
                'description': 'Send a message to Claude',
                'fields': {
                    'message': {
                        'description': 'Message to send',
                        'example': 'What is the weather like?'
                    }
                }
            },
            {
                'domain': 'claude',
                'service': 'analyze_snapshot',
                'description': 'Analyze a Frigate camera snapshot',
                'fields': {
                    'camera': {
                        'description': 'Camera name',
                        'example': 'okam_cam1'
                    },
                    'question': {
                        'description': 'Question about the image',
                        'example': 'What do you see in this image?',
                        'required': False
                    }
                }
            }
        ]
        
        # Note: HA addon services are auto-discovered via API endpoint
        logger.info(f"Services defined: {len(services)}")
    
    async def handle_health(self, request):
        """Health check endpoint"""
        return web.json_response({
            'status': 'ok',
            'service': 'claude_assistant',
            'image_analysis': ENABLE_IMAGE_ANALYSIS
        })
    
    async def handle_chat(self, request):
        """Handle chat requests"""
        try:
            data = await request.json()
            message = data.get('message', '')
            
            if not message:
                return web.json_response({'error': 'No message provided'}, status=400)
            
            logger.info(f"Chat request: {message[:100]}...")
            
            # Execute Claude CLI
            result = await self.run_claude_cli(['chat', message])
            
            return web.json_response({
                'response': result,
                'success': True
            })
            
        except Exception as e:
            logger.error(f"Chat error: {e}")
            return web.json_response({'error': str(e)}, status=500)
    
    async def handle_analyze_image(self, request):
        """Handle image analysis requests"""
        if not ENABLE_IMAGE_ANALYSIS:
            return web.json_response({'error': 'Image analysis disabled'}, status=403)
        
        try:
            data = await request.json()
            image_path = data.get('image_path', '')
            question = data.get('question', 'Describe what you see in this image.')
            
            if not image_path:
                return web.json_response({'error': 'No image_path provided'}, status=400)
            
            # Check if file exists
            if not os.path.exists(image_path):
                return web.json_response({'error': f'Image not found: {image_path}'}, status=404)
            
            logger.info(f"Analyzing image: {image_path}")
            
            # Read image and encode to base64
            with open(image_path, 'rb') as f:
                image_data = base64.b64encode(f.read()).decode('utf-8')
            
            # Use Claude CLI to analyze (simplified - actual implementation may vary)
            prompt = f"{question}\n\nImage: {image_path}"
            result = await self.run_claude_cli(['chat', prompt, '--attach', image_path])
            
            return web.json_response({
                'analysis': result,
                'image_path': image_path,
                'success': True
            })
            
        except Exception as e:
            logger.error(f"Image analysis error: {e}")
            return web.json_response({'error': str(e)}, status=500)
    
    async def handle_analyze_snapshot(self, request):
        """Handle Frigate snapshot analysis"""
        if not ENABLE_IMAGE_ANALYSIS:
            return web.json_response({'error': 'Image analysis disabled'}, status=403)
        
        try:
            data = await request.json()
            camera = data.get('camera', '')
            question = data.get('question', 'Describe what you see. Are there any people or vehicles?')
            
            if not camera:
                return web.json_response({'error': 'No camera specified'}, status=400)
            
            # Find latest snapshot for camera
            snapshot_dir = Path(f'/media/frigate/clips')
            
            # Try to find latest snapshot
            snapshots = list(snapshot_dir.glob(f'{camera}*.jpg'))
            if not snapshots:
                # Try webp format
                snapshots = list(snapshot_dir.glob(f'{camera}*.webp'))
            
            if not snapshots:
                return web.json_response({
                    'error': f'No snapshots found for camera {camera}',
                    'searched_in': str(snapshot_dir)
                }, status=404)
            
            # Get most recent snapshot
            latest_snapshot = max(snapshots, key=lambda p: p.stat().st_mtime)
            
            logger.info(f"Analyzing snapshot: {latest_snapshot}")
            
            # Analyze using Claude
            prompt = f"Camera: {camera}\n{question}\n\nImage: {latest_snapshot}"
            result = await self.run_claude_cli(['chat', prompt, '--attach', str(latest_snapshot)])
            
            return web.json_response({
                'analysis': result,
                'camera': camera,
                'snapshot_path': str(latest_snapshot),
                'success': True
            })
            
        except Exception as e:
            logger.error(f"Snapshot analysis error: {e}")
            return web.json_response({'error': str(e)}, status=500)
    
    async def run_claude_cli(self, args):
        """Execute Claude Code CLI"""
        try:
            # Set environment
            env = os.environ.copy()
            if API_KEY:
                env['ANTHROPIC_API_KEY'] = API_KEY
            
            # Build command
            cmd = ['claude'] + args
            
            logger.debug(f"Executing: {' '.join(cmd)}")
            
            # Run command
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0:
                error_msg = stderr.decode('utf-8')
                logger.error(f"Claude CLI error: {error_msg}")
                raise Exception(f"Claude CLI failed: {error_msg}")
            
            result = stdout.decode('utf-8')
            return result
            
        except Exception as e:
            logger.error(f"Failed to run Claude CLI: {e}")
            raise


async def main():
    """Main entry point"""
    service = ClaudeService()
    await service.start()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Service stopped")
        sys.exit(0)
