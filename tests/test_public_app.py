from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import threading
import unittest
from starlette.testclient import TestClient
from twin.public_app import create_app


class FakeTwin:
    def __init__(self):
        self.estimators={p:SimpleNamespace(artifact={},sparse_policy={}) for p in ("single","multi")}
        self.started=None;self.release=None

    def analyze(self,payload):
        if self.started is not None:
            self.started.set();self.release.wait(5)
        if payload.get("invalid"):raise ValueError("Invalid simulation")
        return {"source":"simulated","request":payload}


class PublicAppTests(unittest.TestCase):
    def setUp(self):self.service=FakeTwin()
    def client(self):return TestClient(create_app(lambda:self.service))

    def test_public_health_static_files_and_headers(self):
        with self.client() as client:
            health=client.get('/api/health')
            self.assertEqual(health.status_code,200)
            self.assertEqual(health.json()['mode'],'public-demo')
            self.assertFalse(health.json()['external_observations_enabled'])
            page=client.get('/')
            self.assertEqual(page.status_code,200)
            self.assertIn('STRATUM',page.text)
            self.assertEqual(page.headers['x-content-type-options'],'nosniff')
            self.assertIn("script-src 'self'",page.headers['content-security-policy'])
            self.assertEqual(client.get('/app.js').status_code,200)

    def test_external_observations_and_private_files_are_not_exposed(self):
        with self.client() as client:
            self.assertEqual(client.post('/api/observations',json={'measurements':{'SG01':1}}).status_code,403)
            self.assertEqual(client.get('/api/telemetry').status_code,403)
            for path in ('/twin/server.py','/data/load-study/multi.joblib','/Civil_Research_Targets_2026.xlsx','/../README.md','/.env'):
                self.assertEqual(client.get(path).status_code,404)

    def test_json_limits_invalid_numbers_and_backend_errors(self):
        with self.client() as client:
            self.assertEqual(client.post('/api/analyze',json={'damage':[]}).status_code,200)
            self.assertEqual(client.post('/api/analyze',json={'invalid':True}).status_code,400)
            for body in (b'{bad',b'[]',b'{"noise": NaN}',b'{"noise": Infinity}'):
                self.assertEqual(client.post('/api/analyze',content=body).status_code,400)
            self.assertEqual(client.post('/api/analyze',content=b'x'*70000).status_code,413)
            self.assertEqual(client.post('/api/analyze',content=iter([b'x'*40000,b'x'*30000])).status_code,413)

    def test_busy_analysis_does_not_block_health_or_queue_more_work(self):
        self.service.started=threading.Event();self.service.release=threading.Event()
        with self.client() as client,ThreadPoolExecutor(max_workers=1) as pool:
            first=pool.submit(client.post,'/api/analyze',json={})
            try:
                self.assertTrue(self.service.started.wait(3))
                second=client.post('/api/analyze',json={})
                self.assertEqual(second.status_code,429)
                self.assertEqual(second.headers['retry-after'],'2')
                self.assertEqual(client.get('/api/health').status_code,200)
            finally:self.service.release.set()
            self.assertEqual(first.result(timeout=3).status_code,200)
            self.assertEqual(client.post('/api/analyze',json={}).status_code,200)

    def test_startup_refuses_an_untrained_or_unaudited_public_demo(self):
        self.service.estimators['multi'].sparse_policy=None
        with self.assertRaisesRegex(RuntimeError,'matching excitation forests'):
            with self.client():pass


if __name__=='__main__':unittest.main()
