"""
MiroFish Backend Entry Point
"""

import os
import sys

# Fix Windows console encoding: set UTF-8 before all other imports
if sys.platform == 'win32':
    os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from app.config import Config


def _check_port_in_use(port: int) -> bool:
    """Return True if another process is already listening on *port*."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        try:
            s.connect(('127.0.0.1', port))
            return True
        except (ConnectionRefusedError, OSError):
            return False


def main():
    """Main function"""
    # Validate configuration
    errors = Config.validate()
    if errors:
        print("Configuration errors:")
        for err in errors:
            print(f"  - {err}")
        print("\nPlease check your .env file configuration")
        sys.exit(1)

    # Get run configuration
    host = os.environ.get('FLASK_HOST', '0.0.0.0')
    port = int(os.environ.get('FLASK_PORT', 5001))
    debug = Config.DEBUG

    # Guard: refuse to start if the port is already occupied
    if _check_port_in_use(port):
        print(f"\n*** Port {port} is already in use — another backend instance is running. ***")
        print(f"    Kill it first:  lsof -ti :{port} | xargs kill -9")
        sys.exit(1)

    # Create application
    app = create_app()

    # Start server
    if debug:
        app.run(host=host, port=port, debug=True, threaded=True)
        return

    try:
        from waitress import serve
        threads = int(os.environ.get('WAITRESS_THREADS', '8'))
        serve(app, host=host, port=port, threads=threads)
    except ImportError:
        app.run(host=host, port=port, debug=False, threaded=True)


if __name__ == '__main__':
    main()
