$ErrorActionPreference = "Stop"

echo "1. Generating Keys..."
mkdir -f keys
python -m genesis_mesh.cli keygen root --output keys/root --key-id rs-1
python -m genesis_mesh.cli keygen network-authority --output keys/na --key-id na-1
python -m genesis_mesh.cli keygen node --output keys/node --key-id node-1

echo "2. Creating Genesis Block..."
python -m genesis_mesh.cli genesis create --network-name "TEST-NET" --root-key keys/root.pub --na-key keys/na.pub --anchor "node-1:localhost:8080" --output genesis_unsigned.json

echo "3. Signing Genesis Block..."
python -m genesis_mesh.cli genesis sign --genesis genesis_unsigned.json --root-private-key keys/root.key --key-id rs-1 --output genesis.json

echo "4. Verifying Genesis Block..."
python -m genesis_mesh.cli genesis verify --genesis genesis.json

echo "5. Info..."
python -m genesis_mesh.cli info --genesis genesis.json

echo "SUCCESS: Full flow completed."
