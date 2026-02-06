import sys
import socket
import asyncio
from threading import Thread
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPixmap
from dashboard_ui import CombinedWindow
from server import WebSocketServer
from qr_utils import generate_qr
from db_pg import login_user, signup_user

PORT = 8765

def get_local_ip():
    """Get local LAN IP address"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    finally:
        s.close()
    return ip


def main():
    app = QApplication(sys.argv)
    
    # Create the combined window
    window = CombinedWindow()
    
    # ---------- ASYNCIO LOOP IN BACKGROUND THREAD ----------
    loop = asyncio.new_event_loop()
    thread = None
    
    def run_loop():
        asyncio.set_event_loop(loop)
        loop.run_forever()
    
    def ensure_loop_running():
        nonlocal thread
        if thread is None or not thread.is_alive():
            thread = Thread(target=run_loop, daemon=True)
            thread.start()
    
    # ---------- SERVER ----------
    server = WebSocketServer(
        port=PORT,
        on_connect=lambda: window.dashboard_view.home_view.set_connected(True),
        on_disconnect=lambda: window.dashboard_view.home_view.set_connected(False),
    )
    
    # ---------- LOGIN HANDLERS ----------
    def handle_login(email: str, password: str):
        user_data = login_user(email, password)
        if user_data:
            window.login_view.set_status("Login successful!", is_error=False)
            # Set username in server for S3 uploads
            server.set_current_user(user_data['username'])
            window.show_dashboard(user_data)
        else:
            window.login_view.set_status("Login failed. Please check your credentials.")
    
    def handle_signup(email: str, password: str):
        username = email.split("@")[0]
        user_data = signup_user(username, email, password)
        if user_data:
            window.login_view.set_status("Account created successfully!", is_error=False)
            # Set username in server for S3 uploads
            server.set_current_user(user_data['username'])
            window.show_dashboard(user_data)
        else:
            window.login_view.set_status("Signup failed. Email may already be registered.")
    
    # Connect login view signals
    window.login_view.login_requested.connect(handle_login)
    window.login_view.signup_requested.connect(handle_signup)
    
    # ---------- LOGOUT HANDLER ----------
    def handle_logout():
        # Stop server if running
        if server.server is not None:
            stop_server()
        
        # Clear username from server
        server.set_current_user(None)
        
        # Clear user data and return to login
        window.dashboard_view.set_user(None)
        window.show_login()
    
    window.dashboard_view.logout_requested.connect(handle_logout)
    
    # ---------- START SERVER ----------
    def start_server():
        ensure_loop_running()
        
        # Generate QR code
        ip = get_local_ip()
        ws_url = f"ws://{ip}:{PORT}/test"
        print("QR URL:", ws_url)
        qr_img = generate_qr(ws_url)
        pixmap = QPixmap.fromImage(qr_img)
        window.dashboard_view.home_view.set_qr(pixmap)
        
        window.dashboard_view.home_view.set_server_running(True)
        asyncio.run_coroutine_threadsafe(server.start(), loop)
    
    # ---------- STOP SERVER ----------
    def stop_server():
        try:
            future = asyncio.run_coroutine_threadsafe(server.stop(), loop)
            future.result(timeout=3)
            
            # Clear QR code
            window.dashboard_view.home_view.clear_qr()
            window.dashboard_view.home_view.set_server_running(False)
        except Exception as e:
            print(f"Error stopping server: {e}")
    
    # Connect server control signals
    window.dashboard_view.home_view.start_server_requested.connect(start_server)
    window.dashboard_view.home_view.stop_server_requested.connect(stop_server)
    
    # Show window and run app
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()