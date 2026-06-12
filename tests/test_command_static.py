import unittest

from diana_omics.commands import build_alignment_smoke_assets, build_raw_samplesheets, fetch_raw_candidate_metadata


class CommandStaticTest(unittest.TestCase):
    def test_raw_status_convention(self):
        self.assertEqual(build_raw_samplesheets.nf_core_status("tumor"), 1)
        self.assertEqual(build_raw_samplesheets.nf_core_status("normal"), 0)

    def test_alignment_sequence_helpers(self):
        self.assertEqual(build_alignment_smoke_assets.reverse_complement("ACGTNacgtn"), "NACGTNACGT")
        self.assertEqual(build_alignment_smoke_assets.wrap_fasta("A" * 81), f"{'A' * 80}\nA")

    def test_raw_candidate_list_is_complete(self):
        self.assertEqual(len(fetch_raw_candidate_metadata.CANDIDATES), 8)
        roles_by_pair: dict[str, set[str]] = {}
        for candidate in fetch_raw_candidate_metadata.CANDIDATES:
            roles_by_pair.setdefault(candidate["pair_id"], set()).add(candidate["role"])
        self.assertTrue(all(roles == {"tumor", "normal"} for roles in roles_by_pair.values()))


if __name__ == "__main__":
    unittest.main()
