import asyncio
import websockets
import json
import os
import wave
import time
import socket
from s3_handler import S3Handler

def get_free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("", 0))  # OS assigns free port
    port = s.getsockname()[1]
    s.close()
    print(port)
    return port

class WebSocketServer:
    def __init__(self, host="0.0.0.0", port=None, on_connect=None, on_disconnect=None):
        self.host = host
        self.port = port
        self.on_connect = on_connect
        self.on_disconnect = on_disconnect
        self.server = None
        self.clients = set()
        self.recording = False
        self.audio_buffer = bytearray()
        self.current_username = None  # Track current user for S3 uploads
        self.s3_handler = S3Handler()  # Initialize S3 handler
    
    def set_current_user(self, username: str):
        """Set the current username for organizing S3 uploads"""
        self.current_username = username
        print(f"📂 Current user set to: {username}")
    
    async def save_audio(self):
        """Save audio locally and upload to S3"""
        if not self.audio_buffer:
            print("No audio to save")
            return None
        
        # Save locally first
        os.makedirs("recordings", exist_ok=True)
        timestamp = int(time.time())
        filename = f"interview_{timestamp}.wav"
        local_path = f"recordings/{filename}"
        
        with wave.open(local_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)   # PCM16 = 2 bytes
            wf.setframerate(16000)
            wf.writeframes(self.audio_buffer)
        
        print(f"✅ Audio saved locally: {local_path}")
        
        # Upload to S3 if user is set
        if self.current_username and self.s3_handler.s3_client:
            result = self.s3_handler.upload_audio_recording(
                local_file_path=local_path,
                username=self.current_username
            )
            
            if result['success']:
                print(f"☁️ Audio uploaded to S3: {result['url']}")
                return {
                    'local_path': local_path,
                    's3_url': result['url'],
                    's3_key': result['key'],
                    'filename': result['filename']
                }
            else:
                print(f"❌ S3 upload failed: {result['message']}")
                return {
                    'local_path': local_path,
                    's3_url': None,
                    'error': result['message']
                }
        else:
            print("⚠️ No username set or S3 not configured, skipping cloud upload")
            return {
                'local_path': local_path,
                's3_url': None
            }
    
    async def handler(self, websocket, path=None):
        self.clients.add(websocket)
        print("Client connected:", path)
        
        if self.on_connect:
            self.on_connect()
        
        try:
            message = {
                "type": "server_message",
                "text": "Mobile connected successfully"
            }
            print(">>> About to send message...")
            await websocket.send(json.dumps(message))
            print(">>> Message sent successfully")
            
            async for message in websocket:
                if isinstance(message, bytes):
                    if self.recording:
                        self.audio_buffer.extend(message)
                        print(f"Recording chunk: {len(message)} bytes")
                
                elif isinstance(message, str):
                    data = json.loads(message)
                    
                    if data["type"] == "start_audio":
                        print("🎙️ Start recording")
                        self.recording = True
                        self.audio_buffer = bytearray()
                    
                    elif data["type"] == "stop_audio":
                        print("🛑 Stop recording")
                        self.recording = False
                        save_result = await self.save_audio()
                        
                        # Send confirmation back to client
                        if save_result:
                            response = {
                                "type": "audio_saved",
                                "local_path": save_result.get('local_path'),
                                "s3_url": save_result.get('s3_url'),
                                "success": True
                            }
                            await websocket.send(json.dumps(response))
        
        except Exception as e:
            print(f"WebSocket handler error: {type(e).__name__}: {e}")
        
        finally:
            print(">>> Handler exiting, removing client")
            self.clients.discard(websocket)
            if self.on_disconnect:
                self.on_disconnect()
    
    async def start(self):
        if self.server is not None:
            print("Server already running")
            return

        # Pick random free port if not set
        if self.port is None:
            self.port = get_free_port()

        self.server = await websockets.serve(
            self.handler,
            self.host,
            self.port
        )

        print(f"WebSocket server running on {self.host}:{self.port}")

    
    async def stop(self):
        if self.server is None:
            return

        print("Stopping WebSocket server...")
        self.server.close()
        await self.server.wait_closed()

        self.server = None
        self.port = None   # 🔥 Reset so next start gets new port

        print("WebSocket server stopped")
