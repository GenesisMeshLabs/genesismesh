"""Certificate revocation list routes for the Network Authority."""

from flask import Blueprint, jsonify

from ..errors import InternalServerError


def create_crl_blueprint(service) -> Blueprint:
    """Create CRL routes bound to a Network Authority service."""
    bp = Blueprint("na_crl", __name__)

    @bp.route("/crl", methods=["GET"])
    def get_crl():
        """Return the active signed certificate revocation list."""
        try:
            crl = service._get_or_create_active_crl()
            return jsonify(crl.model_dump(mode="json"))
        except Exception as exc:
            raise InternalServerError() from exc

    return bp
