#!/usr/bin/env python3
"""
Claude Assistant Service for Home Assistant
Uses Claude Code CLI (no API costs - uses Claude Pro tokens)
"""

import os
import sys
import asyncio
import logging
from aiohttp import web
from pathlib import Path

# Configuration from environment
LOG_LEVEL = os.getenv('LOG_LEVEL', 'info').upper()
ENABLE_IMAGE_ANALYSIS = os.getenv('ENABLE_IMAGE_ANALYSIS', 'true').lower() == 'true'
CLAUDE_CLI = 'claude'  # Installed globally in container

# Setup logging
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('claude_assistant_cli')

class ClaudeService:
    """Claude Assistant using CLI (no API costs!)"""

    def __init__(self):
        self.app = web.Application()
        self.setup_routes()

    def setup_routes(self):
        """Setup HTTP routes"""
        # API endpoints
        self.app.router.add_post('/api/chat', self.handle_chat)
        self.app.router.add_post('/api/analyze_image', self.handle_analyze_image)
        self.app.router.add_post('/api/analyze_snapshot', self.handle_analyze_snapshot)
        self.app.router.add_get('/api/health', self.handle_health)

        # Static files for chat UI
        # Check multiple possible paths
        possible_paths = [
            Path(__file__).parent / 'www',
            Path('/usr/local/bin/www'),
            Path('/www'),
        ]

        www_path = None
        for p in possible_paths:
            logger.info(f"Checking for www directory at: {p}")
            if p.exists() and p.is_dir():
                www_path = p
                logger.info(f"✓ Found www directory at: {p}")
                # List contents
                try:
                    contents = list(p.iterdir())
                    logger.info(f"Contents: {[str(f.name) for f in contents]}")
                except Exception as e:
                    logger.error(f"Error listing contents: {e}")
                break
            else:
                logger.warning(f"✗ Not found or not a directory: {p}")

        if www_path:
            self.app.router.add_static('/static', www_path)
            self.app.router.add_get('/', self.handle_index)
            logger.info(f"✓ Serving static files from: {www_path}")
        else:
            logger.error("✗ No www directory found! Chat UI will not be available.")
            logger.info(f"Script location: {__file__}")
            logger.info(f"Script parent: {Path(__file__).parent}")

    async def handle_index(self, request):
        """Serve chat UI"""
        # Try multiple paths
        possible_paths = [
            Path(__file__).parent / 'www' / 'chat.html',
            Path('/usr/local/bin/www/chat.html'),
            Path('/www/chat.html'),
        ]

        for chat_path in possible_paths:
            if chat_path.exists():
                logger.info(f"Serving chat UI from: {chat_path}")
                return web.FileResponse(chat_path)

        logger.error("Chat UI file not found!")
        return web.Response(text=f'Chat UI not found. Searched: {[str(p) for p in possible_paths]}', status=404)

    async def start(self):
        """Start the service"""
        logger.info("Starting Claude Assistant Service (CLI Mode)")
        logger.info("Mode: CLI - No API costs, uses Claude Pro tokens")

        # Start web server
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', 8099)
        await site.start()

        logger.info("Service started on port 8099")

        # Keep running
        try:
            await asyncio.Event().wait()
        except KeyboardInterrupt:
            logger.info("Shutting down...")

    async def handle_health(self, request):
        """Health check endpoint"""
        return web.json_response({
            'status': 'ok',
            'service': 'claude_assistant_cli',
            'mode': 'cli',
            'api_costs': False,
            'uses_pro_tokens': True,
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

            # Run Claude CLI
            result = await self.run_claude_cli(message)

            return web.json_response({
                'response': result,
                'success': True,
                'mode': 'cli'
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

            if not image_path or not os.path.exists(image_path):
                return web.json_response({'error': 'Invalid image_path'}, status=400)

            logger.info(f"Analyzing image: {image_path}")

            # Use Claude CLI with image reference in prompt
            prompt = f"{question}"
            result = await self.run_claude_cli(prompt, attach_file=image_path)

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
            question = data.get('question', 'Was siehst du? Gibt es Personen oder Fahrzeuge?')

            if not camera:
                return web.json_response({'error': 'No camera specified'}, status=400)

            # Find latest snapshot for camera in Frigate clips directory
            snapshot_dir = Path('/media/frigate/clips')

            # Search for latest snapshot (jpg or webp)
            snapshots = list(snapshot_dir.glob(f'{camera}*.jpg'))
            if not snapshots:
                snapshots = list(snapshot_dir.glob(f'{camera}*.webp'))

            if not snapshots:
                return web.json_response({
                    'error': f'No snapshots found for camera {camera}',
                    'searched_in': str(snapshot_dir)
                }, status=404)

            # Get most recent snapshot
            latest_snapshot = max(snapshots, key=lambda p: p.stat().st_mtime)

            logger.info(f"Analyzing snapshot: {latest_snapshot}")

            # Add instruction to ignore camera overlays
            enhanced_question = f"""WICHTIG: Dies ist ein Überwachungskamera-Bild. Ignoriere alle eingeblendeten Overlay-Elemente wie:
- Blaue oder grüne Erkennungsrahmen
- Prozentangaben und Konfidenzwerte (z.B. "person: 72%")
- Zeitstempel und Datums-Anzeigen
- Kamera-Namen und technische Beschriftungen
- Alle anderen UI-Elemente der Kamera-Software

Konzentriere dich NUR auf die tatsächliche Szene und beantworte diese Frage:
{question}"""

            # Analyze with Claude CLI
            result = await self.run_claude_cli(enhanced_question, attach_file=str(latest_snapshot))

            return web.json_response({
                'analysis': result,
                'camera': camera,
                'snapshot_path': str(latest_snapshot),
                'success': True
            })

        except Exception as e:
            logger.error(f"Snapshot analysis error: {e}")
            return web.json_response({'error': str(e)}, status=500)

    async def run_claude_cli(self, prompt, attach_file=None):
        """Execute Claude CLI command"""
        try:
            # Build command with permissions bypass for file access
            cmd = [CLAUDE_CLI, '--print', '--dangerously-skip-permissions']

            # Add file reference in prompt if provided
            if attach_file:
                prompt = f"Bitte analysiere dieses Bild: {attach_file}\n\n{prompt}"

            cmd.append(prompt)

            logger.debug(f"Running: {' '.join(cmd[:3])}...")

            # Run command with timeout to prevent hanging
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            # Wait with timeout (30 seconds)
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=30.0
                )
            except asyncio.TimeoutError:
                process.kill()
                raise Exception("Claude CLI timeout after 30 seconds")

            if process.returncode != 0:
                error_msg = stderr.decode('utf-8')
                logger.error(f"Claude CLI error: {error_msg}")
                raise Exception(f"Claude CLI failed: {error_msg}")

            result = stdout.decode('utf-8').strip()
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
