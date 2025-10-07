# Troubleshooting

These are instructions intended for advanced users familiar with Linux and SSH. 
Most users should never have to do any of this.

## Tempo Service not running

Check the status of the service:
```bash
sudo systemctl status tempo.service
```

If the service is not running, check the logs for any errors or issues.

## Debugging

View the latest logs for the Tempo service:
```bash
journalctl -u tempo -n 100
```

Tail the logs:
```bash
journalctl -u tempo -f
```

## Restart the Tempo Service

```bash
sudo systemctl restart tempo
```

## Run Tempo Manually

If the Tempo service is not running, try manually running the startup script to diagnose. This should output the logs to the terminal and make it easier to troubleshoot any errors:

```bash
sudo /usr/local/bin/tempo -d
```
