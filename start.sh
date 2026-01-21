#!/bin/bash
set -e

# Role: 'na' (Network Authority) or 'node' (Mesh Node)
ROLE=${SERVICE_ROLE:-na}

if [ "$ROLE" = "na" ]; then
    echo "Starting Network Authority..."
    
    # Check if we have the necessary keys to run
    # In a real deployment, these should be mounted secrets.
    # For this demo/bootstrap, if keys are missing, we run the quickstart generation.
    
    TARGET_GENESIS="genesis.signed.json"
    TARGET_KEY="keys/na.key"
    
    if [ -f "$TARGET_GENESIS" ] && [ -f "$TARGET_KEY" ]; then
        echo "Found existing genesis and keys."
        GENESIS_FILE=$TARGET_GENESIS
        NA_KEY_FILE=$TARGET_KEY
    elif [ -f "demo_genesis.signed.json" ] && [ -f "demo_keys/na.key" ]; then
         echo "Found demo genesis and keys."
         GENESIS_FILE="demo_genesis.signed.json"
         NA_KEY_FILE="demo_keys/na.key"
    else
        echo "No configuration found. Running bootstrap/quickstart..."
        # Run quickstart to generate keys and genesis
        # Ensure the script is executable
        chmod +x examples/quickstart.sh
        # Run it
        ./examples/quickstart.sh
        
        GENESIS_FILE="demo_genesis.signed.json"
        NA_KEY_FILE="demo_keys/na.key"
    fi

    echo "Using Genesis: $GENESIS_FILE"
    echo "Using Key: $NA_KEY_FILE"

    # Start the Flask server
    # Port 5000 is standard for containerized web apps (Azure Container Apps default ingress)
    exec python -m genesis_mesh.na_service \
        --genesis "$GENESIS_FILE" \
        --na-private-key "$NA_KEY_FILE" \
        --host 0.0.0.0 \
        --port 5000

else
    echo "Starting Mesh Node..."
    
    # If args are provided to the script (from container args), pass them through.
    if [ "$#" -gt 0 ]; then
       exec python -m genesis_mesh.node "$@"
    else
        # Default fallback using environment variables
        # This avoids issues with passing complex args via Azure CLI
        echo "Using environment variables for configuration..."
        
        BOOTSTRAP=${BOOTSTRAP_URL:-http://localhost:5000}
        ROLE=${NODE_ROLE:-anchor}
        
        CMD="python -m genesis_mesh.node --bootstrap $BOOTSTRAP --role $ROLE"
        
        # Add persistent flag by default or if env var is set
        if [ "${PERSISTENT:-true}" = "true" ]; then
            CMD="$CMD --persistent"
        fi
        
        echo "Executing: $CMD"
        exec $CMD
    fi
fi
