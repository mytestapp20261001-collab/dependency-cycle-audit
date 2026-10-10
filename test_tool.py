import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("local_tool", HERE / "tool.py")
tool = importlib.util.module_from_spec(spec); spec.loader.exec_module(tool)

class Tests(unittest.TestCase):
    def good(self):
        return json.loads((HERE / "examples/pass.json").read_text())
    def codes(self, data):
        return [item['code'] for item in tool.audit(data)['findings']]
    def test_pass(self):
        self.assertEqual(tool.audit(self.good())['status'], 'pass')
    def test_findings(self):
        self.assertEqual(tool.audit(json.loads((HERE / "examples/fail.json").read_text()))['status'], 'findings')
    def test_malformed_shape(self):
        with self.assertRaises(tool.BadInput): tool.audit([])
    def test_cli_examples(self):
        for name, expected in [('pass',0),('fail',1)]:
            result = subprocess.run([sys.executable, str(HERE/'tool.py'), str(HERE/f'examples/{name}.json')], capture_output=True, text=True)
            self.assertEqual(result.returncode, expected, result.stdout+result.stderr)
            self.assertEqual(json.loads(result.stdout)['schema_version'], 1)
    def test_cli_malformed(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'bad.json'
            for text in ['{', '{"x":1,"x":2}', '{"x":NaN}']:
                path.write_text(text)
                result = subprocess.run([sys.executable, str(HERE/'tool.py'), str(path)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(json.loads(result.stdout)['status'], 'error')
    def test_cli_bad_args(self):
        result = subprocess.run([sys.executable, str(HERE/'tool.py'), '--unknown'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2); self.assertEqual(json.loads(result.stdout)['status'], 'error')
    def test_size_limit(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'big.json'; path.write_text(' '* (tool.MAX_BYTES+1))
            with self.assertRaises(tool.BadInput): tool.load_json(path)

    def test_self_loop(self):
        self.assertIn('self_loop', self.codes({'nodes':['a'],'edges':[['a','a']]}))
    def test_missing_node(self):
        self.assertIn('missing_node', self.codes({'nodes':['a'],'edges':[['a','b']]}))
    def test_duplicate_edge(self):
        data = self.good(); data['edges'] *= 2
        self.assertIn('duplicate_edge', self.codes(data))
    def test_duplicate_node(self):
        with self.assertRaises(tool.BadInput): tool.audit({'nodes':['a','a'],'edges':[]})
    def test_deep_chain(self):
        data = {'nodes':[str(i) for i in range(2000)],'edges':[[str(i),str(i+1)] for i in range(1999)]}
        self.assertEqual(tool.audit(data)['status'], 'pass')
    def test_disjoint_scc(self):
        data = {'nodes':['a','b','c','d'],'edges':[['a','b'],['b','a'],['c','d'],['d','c']]}
        self.assertEqual(tool.audit(data)['summary']['cyclic_components'], 2)
    def test_selfloop_inside_larger_scc_counted_once(self):
        data={'nodes':['a','b'],'edges':[['a','a'],['a','b'],['b','a']]}
        self.assertEqual(tool.audit(data)['summary']['cyclic_components'],1)
    def test_two_selfloops_inside_one_scc(self):
        data={'nodes':['a','b'],'edges':[['a','a'],['b','b'],['a','b'],['b','a']]}
        self.assertEqual(tool.audit(data)['summary']['cyclic_components'],1)
    def test_disjoint_single_and_multi_cycles(self):
        data={'nodes':['a','b','c'],'edges':[['a','a'],['b','c'],['c','b']]}
        self.assertEqual(tool.audit(data)['summary']['cyclic_components'],2)
    def test_empty(self):
        self.assertEqual(tool.audit({'nodes':[],'edges':[]})['status'], 'pass')
    def test_edge_shape(self):
        with self.assertRaises(tool.BadInput): tool.audit({'nodes':['a'],'edges':[['a']]})

    def test_generated_graphs_against_reachability(self):
        import random
        rng = random.Random(712)
        for _ in range(100):
            n = rng.randrange(1, 12)
            edges = [[str(i), str(j)] for i in range(n) for j in range(n) if rng.random() < .12]
            reach = [[i == j for j in range(n)] for i in range(n)]
            for a, b in edges: reach[int(a)][int(b)] = True
            for k in range(n):
                for i in range(n):
                    for j in range(n): reach[i][j] |= reach[i][k] and reach[k][j]
            expected, seen = [], set()
            for i in range(n):
                if i in seen: continue
                component = [j for j in range(n) if reach[i][j] and reach[j][i]]
                seen.update(component)
                if len(component) > 1: expected.append(component)
            observed = [f['node_indices'] for f in tool.audit({'nodes':list(map(str,range(n))), 'edges':edges})['findings'] if f['code'] == 'dependency_cycle']
            self.assertEqual(expected, observed)

if __name__ == "__main__": unittest.main()
