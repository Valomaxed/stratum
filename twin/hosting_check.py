"""Fail the image build when its native model artifacts cannot serve the demo."""
import json
from .server import TwinService
from .public_app import ready


def main():
    service=TwinService()
    if not ready(service):raise RuntimeError("Model, excitation signature, or audited sparse policy is unavailable")
    result=service.analyze({"protocol":"multi","physics":True,"refinement":"sparse","noise":0,"drift":.01})
    physics=result["prediction"]["physics"]
    if physics.get("method")!="Noise-aware sparse physics" or physics["detected_members"]:
        raise RuntimeError("Native serving check failed")
    print(json.dumps({"ready":True,"protocols":["single","multi"],"sparse_healthy_check":True}))


if __name__=="__main__":main()
