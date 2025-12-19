# Tempo Installation

Note: If you don't want to use a pre-built image, you can copy this repo to a Raspberry Pi Zero 2 W running 
Raspberry Pi OS and run ./install/install.sh to set up Tempo manually.

1. Download the Tempo OS image from: https://filament.reviews/tempo.img.zip
2. Install the Raspberry Pi Imager from the [official download page](https://www.raspberrypi.com/software/)
3. Insert the target SD Card into your computer and launch the Raspberry Pi Imager software
    - Raspberry Pi Device: Choose Raspberry Pi Zero 2 W
    - Operating System: Scroll all the way to the bottom and select 'Use Custom'
    - Select the Tempo OS image you downloaded earlier
    - Storage: Select the target SD Card
4. After it completes writing, eject the SD Card and insert it into the Raspberry Pi Zero 2 W.
5. Power on the Raspberry Pi with the Inky Impression display connected. It will take a few minutes on first boot to expand the filesystem and start the setup process. You'll see the eInk screen update with the Tempo logo and Wi-Fi setup instructions.
6. After waiting a minute or two, a new 'Wifi Connect' access point will be created. Follow the on-screen instructions to complete the Wi-Fi setup and initial configuration.
7. Once wifi set-up is complete, from your computer connect to http://tempo.local in your web browser to access the Tempo web interface and configure your calendar.
