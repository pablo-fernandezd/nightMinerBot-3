# 🤖 Midnight Scavenger Mine Bot (CIP-

# Signature Automation)

## ⚠ EXCLUSIVE DISCLAIMER (PLEASE READ

## CAREFULLY)

#### USE OF THIS SOFTWARE IS AT YOUR OWN RISK AND SOLE RESPONSIBILITY.

```
● This script is an automation tool created for educational and research
purposes regarding the interaction of Selenium and cryptography (CIP-8) on
web forms.
● The author does not guarantee its functionality, legality, or suitability
for any purpose.
● The script contains private keys within the generated JSON files. If someone
gains access to these files, they could steal the funds from the associated
wallet.
● Exemption from Liability: By using this code, you agree that the author
( JJTEZANOS ) and collaborators are exempt from any liability for loss of
funds, account bans, or any other adverse legal or financial consequence
that may arise.
● You are responsible for complying with the terms of service of the website
( sm.midnight.gd ) and with the applicable laws in your jurisdiction.
● 🚨 IT IS STRONGLY RECOMMENDED NOT TO USE THIS SOFTWARE WITH
WALLETS CONTAINING VALUABLE FUNDS. 🚨
```
## 🛠 Installation and Usage Instructions

### 1. Dependency Installation

Ensure you have **Python 3.10+** installed.
Use pip to install the necessary libraries:
pip install -r requirements.txt

### 2. Bot Execution

**Important:** Make sure the wallet_pool folder is empty (or delete it) if you want to **generate
new wallets** before execution.
Run the main script using the following command:


python lanzador_bots.py
The script will guide you through the following steps:

1. It will ask you for the **number of wallets** to generate/run.
2. It will generate the wallets with their **Payment** and **Staking** keys.
3. It will start a **Selenium** bot (in _headless mode_ ) for each wallet.
4. The bot will automate the process of navigation, address pasting, and simulating the
    **CIP-8 signature** (Payment Key), along with pasting the public key (64 chars), using
    **JavaScript** and manual editing simulation to avoid validation errors.

### 3. Debugging and Verification

If the bot fails during the process, you can review the content of the corresponding
wallet_pool/wallet_X.json file.
This file contains:
● The address
● The public_key_hex (public key in hexadecimal format)
● The generated_signature (generated signature)
You can use this information to debug or manually verify the process on the web if needed.

## ❤ Project Support

If this tool has been useful to you for advancing or understanding the complexity of **CIP-
signatures** on Cardano, please consider giving a star (⭐) to the repository! Your support is
welcome!


