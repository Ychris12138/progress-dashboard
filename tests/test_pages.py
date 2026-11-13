import tempfile
from pathlib import Path
import unittest
from dashboard.core import Error, atomic_json
from dashboard.pages import decision, eligible, assert_empty

ROOT = Path(__file__).resolve().parents[1]

class PagesCase(unittest.TestCase):
    def test_only_main_push_or_dispatch(self):
        for event in ('pull_request', 'pull_request_target', 'push', 'workflow_dispatch'):
            for ref in ('refs/heads/main', 'refs/heads/test', 'refs/tags/main'):
                self.assertEqual(eligible(event, ref), event in ('push','workflow_dispatch') and ref == 'refs/heads/main')

    def test_old_run_cannot_replace_current_main(self):
        self.assertEqual(decision('old', 'new', [], lambda a,b: False)[0], False)

    def test_previously_deployed_descendant_blocks_force_rewind(self):
        self.assertFalse(decision('old','old',['new'],lambda a,b: (a,b)==('old','new'))[0])

    def test_divergent_deployed_history_fails_closed(self):
        with self.assertRaises(Error): decision('other','other',['new'],lambda a,b: False)

    def test_initial_and_forward_and_same_commit_allowed(self):
        self.assertTrue(decision('new','new',[],lambda a,b: False)[0])
        self.assertTrue(decision('new','new',['old'],lambda a,b: (a,b)==('old','new'))[0])
        self.assertTrue(decision('new','new',['new'],lambda a,b: False)[0])

    def test_nonempty_public_data_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve()
            atomic_json(root/'public/projects.json',{'schema_version':1,'projects':[]})
            assert_empty(root)
            atomic_json(root/'public/projects.json',{'schema_version':1,'projects':[{
                'schema_version':1,'project_id':'proj_demo','public_name':'合成项目','category':'other','aliases':[]}]})
            with self.assertRaises(Error): assert_empty(root)

    def test_workflow_static_guards_and_pinned_actions(self):
        import re
        text=(ROOT/'.github/workflows/pages.yml').read_text()
        self.assertIn('needs: [test, frontend, build]',text)
        self.assertIn('queue: max',text)
        self.assertNotIn('cancel-in-progress: true',text)
        self.assertIn('permissions: {}',text)
        self.assertIn('python scripts/assert_empty.py',text)
        self.assertIn("if: steps.guard.outputs.deploy == 'true'",text)
        self.assertNotIn('pull_request_target:',text)
        self.assertNotIn('always()',text)
        for ref in re.findall(r'uses: (\S+)',text):
            self.assertRegex(ref,r'^actions/[\w-]+@[0-9a-f]{40}$')
        for job in ('test','frontend','build'):
            segment=text.split('\n  '+job+':',1)[1].split('\n  deploy:',1)[0]
            if job=='test': segment=segment.split('\n  frontend:',1)[0]
            elif job=='frontend': segment=segment.split('\n  build:',1)[0]
            self.assertNotIn('write',segment)
