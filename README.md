# BMW MGU App Manager v0.2
Read-only Windows SSH compatibility checker for BMW MGU / iDrive 8. This is not an app installer yet.

## Download Windows EXE
Open **Actions** → **Build Windows EXE** → latest successful run → **Artifacts** → **BMW-MGU-App-Manager-Windows**.

## Run from source
Python 3.12+: `python mgu_manager.py`. Windows OpenSSH Client and an existing authorized SSH private key are required for connection checks.

Do not upload SSH keys, passwords, vehicle reports containing private information, or proprietary packages to this public repository.

The program only queries system information over SSH and inspects local package manifests. It does not flash or modify the vehicle. Actual custom-app deployment compatibility is unverified.
