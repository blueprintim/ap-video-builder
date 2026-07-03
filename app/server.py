"""
server.py
Flask app exposing POST /build_product_page.

This is written so it can either run standalone (python -m app.server) or have
its blueprint registered inside the existing crane_render app:

    from app.server import bp as build_product_page_bp
    existing_app.register_blueprint(build_product_page_bp)

Auth: a shared secret in the X-Build-Token header (env BUILD_API_TOKEN), so only
your Make scenario can invoke it. Publishing to the live server only happens when
the request is authenticated AND payload publish is not explicitly false.
"""

from __future__ import annotations
import os
from flask import Flask, Blueprint, request, jsonify

from .builder import build_product_page, BuildError
from .publisher import SFTPPublisher, LocalMockPublisher
from .sirv import SirvClient, SirvError

bp = Blueprint("build_product_page", __name__)

# Map logo_key -> media sub-folder used in media_path. Adjust to your taxonomy.
PRODUCT_GROUP_DIR_MAP = {
    "hiab": "hiab-boom-trucks",
    "moffett": "moffett-forklifts",
    "palfinger": "palfinger",
    "multilift": "multilift-hooklifts",
}


def _check_auth(req):
    expected = os.environ.get("BUILD_API_TOKEN")
    if not expected:
        return True  # no token configured -> allow (dev). Set one in prod.
    return req.headers.get("X-Build-Token") == expected


def _make_publisher():
    # If SFTP env is set, use it; else fall back to a local mock dir (dry-run).
    if os.environ.get("SFTP_HOST"):
        return SFTPPublisher(), False
    mock_root = os.environ.get("MOCK_PUBLISH_DIR", "/tmp/cpb_publish")
    return LocalMockPublisher(mock_root), True


def _make_sirv():
    try:
        return SirvClient()
    except SirvError:
        return None  # no Sirv creds -> skip video upload (video still concatenated)


@bp.route("/build_product_page", methods=["POST"])
def build_endpoint():
    if not _check_auth(request):
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    payload = request.get_json(silent=True) or {}
    publish = payload.get("publish", True)

    publisher, is_mock = _make_publisher()
    sirv = _make_sirv()

    try:
        result = build_product_page(
            payload,
            publisher=publisher,
            sirv=sirv,
            product_group_dir_map=PRODUCT_GROUP_DIR_MAP,
            publish=publish,
        )
    except BuildError as e:
        return jsonify({"ok": False, "stage": e.stage, "error": str(e)}), 422
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "stage": "unexpected", "error": str(e)}), 500
    finally:
        if hasattr(publisher, "close"):
            try:
                publisher.close()
            except Exception:  # noqa: BLE001
                pass

    result["dry_run"] = is_mock or not publish
    # Don't ship the full page HTML back by default -- keep the response small.
    result.pop("page_html", None)
    return jsonify(result), 200


def create_app():
    app = Flask(__name__)
    app.register_blueprint(bp)
    return app


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
