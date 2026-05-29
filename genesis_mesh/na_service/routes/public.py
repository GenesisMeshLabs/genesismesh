"""Public read-only Network Authority routes."""

from flask import Blueprint, jsonify


def create_public_blueprint(service) -> Blueprint:
    """Create public metadata routes for genesis and policy documents."""
    bp = Blueprint("na_public", __name__)

    @bp.route("/genesis", methods=["GET"])
    def get_genesis():
        """Return the genesis block."""
        return jsonify(service.genesis_block.model_dump(mode="json"))

    @bp.route("/policy", methods=["GET"])
    def get_policy():
        """Return the active signed policy manifest."""
        policy = service.db.get_active_policy()
        if policy is None:
            policy = service._get_default_policy()
            service.db.save_policy(policy, active=True)
        return jsonify(policy.model_dump(mode="json"))

    return bp
