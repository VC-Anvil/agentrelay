"""HTTP ticket context exposes historical checks only in the selected project."""
from http.client import HTTPConnection
import json
from pathlib import Path
import tempfile
import threading
import unittest

from agentrelay.server import AppServer
from agentrelay.snapshots import create_snapshot
from agentrelay.source_checks import check_sources
from agentrelay.store import Store
from agentrelay.workspaces import Workspace


class HTTPSourceChecksTests(unittest.TestCase):
    def test_context_is_bounded_historical_and_project_scoped(self):
        with tempfile.TemporaryDirectory(prefix='agentrelay-http-source-checks-') as directory:
            root = Path(directory)
            sources = root / 'sources'
            sources.mkdir()
            (sources / 'input.txt').write_text('original', encoding='utf-8')
            captured = create_snapshot(sources, ['input.txt'], root / 'snapshot')
            stores = {key: Store(root / (key + '.sqlite')) for key in ('alpha', 'beta')}
            for name, store in stores.items():
                store.action('create_ticket', {'title': name, 'acceptance': ['Independent review']})
            before = stores['beta'].state()
            receipts = []
            for number in range(4):
                receipts.append(check_sources(stores['alpha'], ticket_id='AR-0001',
                    expected_revision=1, snapshot=root / 'snapshot',
                    expected_snapshot_id=captured['snapshot_id'], root=sources,
                    request_id=f'http-check-{number}', actor='agent:fixture'))
            current = stores['alpha'].action('update_ticket', {'id': 'AR-0001',
                'expected_revision': 1, 'description': 'Changed after the historical check'})
            (sources / 'input.txt').write_text('changed after checking', encoding='utf-8')
            spaces = {name: Workspace(name, name, store) for name, store in stores.items()}
            server = AppServer(('127.0.0.1', 0), stores['alpha'], workspaces=spaces,
                               default_workspace_id='alpha')
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()

            def request(workspace, method='GET', path='/api/tickets/AR-0001/context', data=None):
                connection = HTTPConnection('127.0.0.1', server.server_port, timeout=5)
                headers = {'X-AgentRelay-Client': 'browser', 'Content-Type': 'application/json'}
                if workspace is not None:
                    headers['X-AgentRelay-Workspace'] = workspace
                try:
                    connection.request(method, path, json.dumps(data) if data else None, headers)
                    response = connection.getresponse()
                    return response.status, json.loads(response.read())
                finally:
                    connection.close()

            try:
                self.assertEqual(request(None)[0], 400)
                code, context = request('alpha')
                self.assertEqual(code, 200)
                self.assertEqual(context['ticket'], current)
                self.assertEqual(context['source_checks_page'], {
                    'total': 4, 'count': 3, 'limit': 3, 'next_before_id': receipts[1]['check_id']})
                self.assertEqual([item['check_id'] for item in context['source_checks']],
                                 [item['check_id'] for item in reversed(receipts[1:])])
                for item in context['source_checks']:
                    self.assertFalse(item['ticket_revision_matches_now'])
                    self.assertEqual(item['summary']['unchanged'], 1)
                    self.assertNotIn('report', item)
                code, other = request('beta')
                self.assertEqual(code, 200)
                self.assertEqual(other['source_checks'], [])
                self.assertEqual(other['source_checks_page']['total'], 0)
                self.assertEqual(stores['beta'].state(), before)
                denied = request('alpha', 'POST', '/api/actions', {
                    'action': 'record_source_check', 'data': {'report': {'forged': True}}})
                self.assertEqual(denied[0], 400)
                self.assertEqual(request('alpha')[1]['source_checks_page']['total'], 4)
                self.assertEqual(stores['alpha'].context('AR-0001')['ticket'], current)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(3)


if __name__ == '__main__':
    unittest.main()
