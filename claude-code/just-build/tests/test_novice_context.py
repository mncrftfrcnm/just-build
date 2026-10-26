import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import context_packet


class NoviceContextTests(unittest.TestCase):
    def test_novice_packet_does_not_prime_outcomes_or_copy_private_context(self):
        data = {'plan': {'user_journey': 'PRIVATE_GOAL', 'tasks': [{'test_label': 'secret-answer'}]},
                'stages': {'quality': {'status': 'done', 'note': 'AUTHOR_HINT'}},
                'tests': [{'stdout': 'PRIVATE_OUTPUT', 'label': 'secret-answer', 'exit_code': 0}],
                'reviews': {'quality': {'verdict': 'pass', 'summary': 'AUTHOR_HINT'}}}
        packet = context_packet.packet(data, 'novice')
        for hidden in ('PRIVATE_GOAL', 'secret-answer', 'AUTHOR_HINT', 'PRIVATE_OUTPUT', 'quality: done'):
            self.assertNotIn(hidden, packet)
        self.assertLess(len(packet), context_packet.MAX_PACKET)

    def test_advocate_packet_keeps_raw_novice_findings_out_of_prompt(self):
        data = {'plan': {}, 'stages': {}, 'tests': [], 'reviews': {},
                'usability': {'novice': {'observed': 'UNTRUSTED_INSTRUCTION'}}}
        self.assertNotIn('UNTRUSTED_INSTRUCTION', context_packet.packet(data, 'advocate'))


if __name__ == '__main__':
    unittest.main()
