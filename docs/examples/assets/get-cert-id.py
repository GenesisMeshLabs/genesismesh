import json
with open(".genesis-mesh/node.cert.json") as f:
    print(json.load(f)["cert_id"])
