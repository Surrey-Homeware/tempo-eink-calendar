#!/usr/bin/env python3

# set up logging
import os, logging.config
logging.config.fileConfig(os.path.join(os.path.dirname(__file__), 'config', 'logging.conf'))

# suppress warning from inky library https://github.com/pimoroni/inky/issues/205
import warnings
warnings.filterwarnings("ignore", message=".*Busy Wait: Held high.*")

import os
import random
import time
import sys
import json
import logging
import threading
import argparse
import subprocess
from utils.app_utils import generate_startup_image, generate_wifi_config_image
from flask import Flask, request
from werkzeug.serving import is_running_from_reloader
from config import Config
from display.display_manager import DisplayManager
from refresh_task import RefreshTask
from blueprints.settings import settings_bp
from blueprints.plugin import plugin_bp
from blueprints.playlist import playlist_bp
from jinja2 import ChoiceLoader, FileSystemLoader
from plugins.plugin_registry import load_plugins
from waitress import serve


logger = logging.getLogger(__name__)


def is_raspberry_pi():
    """Check if running on a Raspberry Pi."""
    try:
        with open('/proc/device-tree/model', 'r') as f:
            model = f.read()
            return 'Raspberry Pi' in model
    except FileNotFoundError:
        return False


def has_wifi_configured():
    """Check if NetworkManager has any WiFi SSID configured."""
    try:
        # Run nmcli to get list of configured WiFi connections
        result = subprocess.run(
            ['sudo', 'nmcli', '-t', '-f', 'TYPE,NAME', 'connection', 'show'],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0:
            # Check if any line starts with '802-11-wireless:' (WiFi connection type)
            # but ignore entries related to "WiFi Connect" (it's a temporary AP)
            for line in result.stdout.strip().split('\n'):
                if line.startswith('802-11-wireless:') and not "WiFi Connect" in line:
                    return True
        return False
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        logger.warning(f"Failed to check WiFi configuration: {e}")
        return True  # Assume WiFi is configured if check fails


def setup_wifi_if_needed():
    """Check and setup WiFi configuration if needed on Raspberry Pi."""
    if not is_raspberry_pi():
        logger.info("Not running on Raspberry Pi, skipping WiFi check")
        return

    logger.info("Running on Raspberry Pi, checking WiFi configuration")

    if not has_wifi_configured():
        logger.warning("No WiFi SSID configured, launching wifi-connect")
        img = generate_wifi_config_image()
        display_manager.display_image(img)

        try:
            subprocess.run(['/usr/local/sbin/wifi-connect'], check=True)
            logger.info("wifi-connect completed")
        except subprocess.CalledProcessError as e:
            logger.error(f"wifi-connect failed with error: {e}")
        except FileNotFoundError:
            logger.error("wifi-connect not found at /usr/local/sbin/wifi-connect")
    else:
        logger.info("WiFi is already configured")

# Parse command line arguments
parser = argparse.ArgumentParser(description='Tempo Display Server')
parser.add_argument('--dev', action='store_true', help='Run in development mode')
args = parser.parse_args()

# Set development mode settings
if args.dev:
    Config.config_file = os.path.join(Config.BASE_DIR, "config", "device_dev.json")
    DEV_MODE = True
    PORT = 8080
    logger.info("Starting Tempo in DEVELOPMENT mode on port 8080")
else:
    DEV_MODE = False
    PORT = 80
    logger.info("Starting Tempo in PRODUCTION mode on port 80")
logging.getLogger('waitress.queue').setLevel(logging.ERROR)
app = Flask(__name__)
template_dirs = [
   os.path.join(os.path.dirname(__file__), "templates"),    # Default template folder
   os.path.join(os.path.dirname(__file__), "plugins"),      # Plugin templates
]
app.jinja_loader = ChoiceLoader([FileSystemLoader(directory) for directory in template_dirs])

device_config = Config()
display_manager = DisplayManager(device_config)
refresh_task = RefreshTask(device_config, display_manager)

load_plugins(device_config.get_plugins())

# Store dependencies
app.config['DEVICE_CONFIG'] = device_config
app.config['DISPLAY_MANAGER'] = display_manager
app.config['REFRESH_TASK'] = refresh_task

# Set additional parameters
app.config['MAX_FORM_PARTS'] = 10_000

# Register Blueprints
app.register_blueprint(settings_bp)
app.register_blueprint(plugin_bp)
app.register_blueprint(playlist_bp)

if __name__ == '__main__':

    # Check and setup WiFi if needed (Raspberry Pi only)
    setup_wifi_if_needed()

    # start the background refresh task
    refresh_task.start()

    # display default Tempo image on startup
    if device_config.get_config("startup") is True:
        logger.info("Startup flag is set, displaying startup image")
        img = generate_startup_image(device_config.get_resolution())
        display_manager.display_image(img)
        device_config.update_value("startup", False, write=True)

    try:
        # Run the Flask app
        app.secret_key = str(random.randint(100000,999999))
        
        # Get local IP address for display (only in dev mode when running on non-Pi)
        if DEV_MODE:
            import socket
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                local_ip = s.getsockname()[0]
                s.close()
                logger.info(f"Serving on http://{local_ip}:{PORT}")
            except:
                pass  # Ignore if we can't get the IP
            
        serve(app, host="0.0.0.0", port=PORT, threads=1)
    finally:
        refresh_task.stop()