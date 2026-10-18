"""First-policy immutable API fixtures; no target writes or paid calls."""
import base64
import copy
import hashlib
import json
import sys
import unittest
import zlib
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import workflow_common_quality as quality
import workflow_control as control
import workflow_devtools_bootstrap as bootstrap

ROOT = Path(__file__).resolve().parents[1]
SOURCE, HEAD = "c" * 40, "d" * 40
BASE_TREE = json.loads(zlib.decompress(base64.b64decode('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')))
MAIN_TREE = json.loads(zlib.decompress(base64.b64decode('eJy9XWtvHMex/SuBPodkd/WjqvPN12YCA4kcWDIuLi4uiOruanHj5S6zu5QtB/nvqV5Z9oxEiT3CHQmCxNfunDlTXXVO9YP/ena85Wd/+sMzcjl5BODknK3kXMvWJ1t8sabaFL01VPR7z/74h2cPh21/ye3pdH/809UV328uX21Otw/5suzvrg5yvz9ebTevbk+7ze7VxeZ0Vfa7E292crgQufjpYVf1oyqvT/v99njxkDfpSl9/dTqIHK+WAOmvUCT/+69n93y67ZgusxxP9wcup02R4+U/jvtd/8G7fe0/+MwaE70/v/TN/fkrebvP/fNfaUhsk7AJIWAx2WNxucWaQVqpxmSiKNlFK+eXbH7pb+FTMuuR0vEdr4Zh/fuPf5iQoW/321WmNBhv9M+UhjOTv9NQ9Cf0Ygk8J2nRVVPAe6kpEpWaU2ie9JO2ejQMA/n4jV9NP1keEZY9x+wM1YginX8U0itjZEox2wzVss1tEhGBYO2AGEY15+UtgGWhgCZkpGQ9o68NITcj3KqDVKhBipCDSA7rh8IokMdu+err7765/u6/n19//2LR0xcTXbHYfMiGoZSG4ksBx9k50EjEzKFJocnTt96v/fSHUT1KxbcvXvxwffPy+m9//+tXL68XBUNzlNj7FqIpJZInNhUjsnGNE7rijDRDCVcPhmEgAwxcHaU8HDanNxcH4aoAjsfLu7ooTEohSUUTsz4XMD6F0oI3kaovTkFRytEF66ZhQjatHSbDqB4lqejN/7woOjTpoNWYZEaylJw3Ih41UZsakm22CraK7FePjmEgH7/xq/vD/u7+dFxEQAy55F6knGqW6kNBaISh5MregmbpUh02sz4Bw0CeJkCh3End8Ekuyv5+s92flg4OyGhZYy9zhGAzeQHRcWvBJnC+uqbj1CXI0xyqhWzt0TEMa4ij1xv56UJ+VuF5catZZClHSFhFL+tsYytFEaRahFFU+LKPgDayK2SmHIF1a3M0DOsTHB3LrdzxwoHUtJAxGgTWTK96JjC0oMW/qPylZILGsK+Z1h9Io0CeJuDq9+i4eBsvl2+/s1yTVk3nJhkOqKmNvYsNOfksQPph1XIorok+s5kqsbR2tAzD+ghZ5+xysdkdT4cHNXD73eI63AViFo4lqT9y6G2oEvXKLVStfSoPU4jJVZ4Qk/zqYn0Y1aO83D9stzcH+eeDOtubk9zdbzUXLyWmm+kkZEoSATVRviYkVY5U1CZwEBsNUGzTiIGIq9vaUVSPEvPT/vBj2+5/WphaKCnlJmII3oWWxGHOORUNzRZjSFUfExQH66eWUSCfvvm3SeZdbb54V6119Fy+udsuU7FGlHtCronUYRnH0WT1kVVUJQKBouLGXKdB4imtbneGcT3J1Ltr5ofNtl7cP+Tt5ni7mCeKxmBDap5MDDYIFjUbDREguMDigzEsYSZojIt2bZ6GcS3jaXkcBROaM+S4eR3WiNgkUUoKo1KO3CyKatOpG3KJVs82w7CG6SmbxdxYUyibClRUdEImqTHWkjTEm1DuvSzMwUmYxo51q4vhYVjD3LSHX35ZzI6LNVhurYFxFSDmZFpBNFzIssneltKcjzMZ7CCszc4wrGF2TofN6zfLg6cZ1qGtgYwxUWZJ2FoOrAK9BWmOPQGXOE084HB1eoZhPUnPuxp2dlMHaQf5jPQsKs2jQFILDL5azKolVHyZhFlccsmqhKf89i3eNWPAxdXN1DCuRTR9Dj0qRL0+Jp+Tj6U4TLlKJdtiLpERHanomltNZ8P6Xc1RYE/x83A4yO4tP0fVQfrB4WG5GqpEuaoOCzrig5TgWb1vUIDqfI16wZY8cQt26iWChvzqLmsU1xM07e9ldzy2i2PZH6TwYXmdzxyyc9WXSFiBo5fgQDh4sRWyMaAaFs0sW4MNqxM0DOsJgnpzZ3+Sfh3Z7u8vTvuLO8WwmCag7vsIk82ZXEkqxSo3aq6m5ouNjRESzwIJwLvV5eIwrid4OshW+CgXWXPShz2OxeK6RaMhzhrGmNGi2sACPhAgO4aoqUiLTHaz+bao8np1cT2K60m2dvvXvZv66kHHnNQLfjjt7+TwSpZnKNu0ZlgPao6aj56aVR2XQ1UrreJfrBRBRTzN5CHA6kJ7GNcTVB3ljnenTbn4NcKWE+RjK8ZGNiScMcTex+y1VnW+VzCsFbi6FmdGxK/Pzyisp/i55UMPoONRTsf/h3hSG5SKYsmQA0bX5S7HFCOiz17NJWaCBAGmQ89RWD1RDeN6iq83u3JO4T2V/5rVF5PECYOrpI4RCqYmLesjUwROs1DuvStHrA8YZxrc4OqTfcO4PiBp82qnCmDZdIVrVQS1RBi0tfiWGQCzCxaLl2IVhhDCbFo8rN5/HkY1p2C7OS3qIIZkNJ9RzOKjeKaq7i+YDOTVJCKCc9mpZ15/cmIYyAf3e3UeBbwrcjwd3nzGMimIQhpaldDFVKrRHFYyalJL6MGXEIMxKU777IDrt5NHUX3Ix/3D8fY8/f8ZZFRnk/caaD4bMKjFrc8sVmTV4pkCF+s0f7WpvrP6iFavMqOwPmTjfOXNaX9Y3qIgm2OVotqxYDaxj8Xo1MFpmdOrhVitj8aQm/e31ldvo7DmZNzx4ce6/2m33aifLNsNXL7hpS2tlFispQaBLJmmhSxbtSOaoIHU3OoTiSAyi464+pTUMKo5H7v7u0NZOKeglTmrTVVLJpqPHXiyRVhdGEjl6FQfZjJTTeFWv/thUPO7vz/0NRB3dxuNhf2ubV4tjwZSv46g18xZAqoqLhR9iqFJjd6lprgoMc68YFp/dIyimvPxqyxfGBHNZOZkHBtO0Ff6Or1cswENFeM56SNQ616nHXAXVpdPw6jmFPQA6MlhmYRk0nKEuRaqMWaMIarRZuttSjUU9QCUvDqkWWdpdf04CmpGwFd/uX7+8sXS2eiqZlqaac30ZXstBdWqLYdcvG0VHHtIapBmBDg0X8C4juKacdCXlt589+ebr797/s0PX79cvjwqayqumdiKgI458LlmW2KLAWxs3mAJpU0rple/s3p3aBTWe1w8f/n9t//1w8tvn/9lKRFae0pOUQcbtKAFKnq0wVbDjfXLkVo1KYuZikoV86sTMQxrRsQ3+/KjHNpmu8xYsQ65JqYa8b00+ZTQEvReuMajk5AopyAym4InVbfru8tBXDMS/vrt19fPX1wvY8AzVjaBGb0IOxNtLNAiSm9LerDWAsY4a2qZuL69HoU1I+C7v+v9v/jz0pFgKGctSCWKjj9nba7q7imZpBKtaY5KfYLWzRox+lhWLxHDsGYcfH/91Td/u168otpVKECNQOPMhySALpNPCLV6Ei4NNU3LNCumZFenYBjWexT89fqrF4s5gAgUjKoOrUHkpfeZkZX/kJstHkIKVnORzMIA1udgGNZjHNw8/+7l9WLBUNStRUqab1vQC1RXRBOyFevVuoCpVus1l0SzAfEF1iUNopoR8eL66x++//bl/yzlIIpPqkGtKNW+5hoyghFsAKUR1rOdNZGm1sGrelubhGFYMxI0Bj5HIqSY+8DTv8aqQyWxJSPb2Gc1VKLV5FswMO870vrVcRjWjIOy327l7TrXRf3HihKNbdClqkZYN7LoUGuR0zxkEbVU1awFe/X+4zCQj9321b41dU9y0Ze3bvrSxd3peLlV6bR8ktU5fdA2ctO400FYup8LsbLtk3QRPOj3TZwKJ2/WXxI9DOs9in5bJ6RvWm7140URUpo1nJkEXFNPU2wwAVOS5KxPDnJqFKOUL7B9cxTIU7d/dc/lR34ly7uzAT0ZVS3UO+Wo/oWM86rpk1p6F2rQFF7U9E/bDWH9rVnDqJ4mZnd/d/F2yCxtRkUwVFWwiYrXKhGi4UpFdW4MrVHRwmbYOjdrRpng/OqjZhjYGDt9BvCoASSf0b1tYDMHMqA6B0Gcqjut9prWognG+gLqCMVMZ5CDWX07+DCqGT91X5YVGopW9Y14QIFmm7QubPqqYtSiDhXAiSiDX+BMgFEgH9zv1ee5Dys9W+tAtAFdbagKN2EIDUyiFkKE3DvH85UVZFbXWsOwPuSB67ITAGrO1vZpEdtn2D2z8zr6AoVqSGVejJZFVf/6WxmHgTx6z59abrMwJjiotEmFS1TZn23w6oG1kKnqQxc8cs7qf1loVkhw9VwwDOtDfm73x9PFPfetz0vJcH0Ra+IK1qJIrapyOXpnqRmv4Vg1RweJ8/2Kcf0dEMOwZmT8qi3eVtHFAkNiTs6rzwkFJQQXMUip6pCjVVOo1qeAdWqQZv1bjG71bvYwsMfI+Iw1AdSqlmeXwFdSpVuSAZ98IsjWqC8MoFGomnvavl1/amsY1XsknMqtLKuWpUloxRS1fRSAckykvEeMqSaOWUPPQsuwvi0bBvLYLV+93j1cnA9E6Atf70WvtCsbOV6ev79slgdbbAJqhg1DAy4lZFQ03pTWsNXCEsjh1JIFgvXXT4/CmtHzro4sHxelgcr8Sq5WJCQvOvShROzL2q2olq19/TZNjxSyltaf8RzG9R4P7zn1hVM8VCKw49bAt24NLZXGAEJZdZxGbh+tNN2aYQ2E9R3HMLCPk3H6edkscM89fXOVV/2OqIYnWx2ZsZK3fd9D5OBsCjTbkktp9bURw7BmTBzLYbP0tIxQVKm0ru/AGd9P8UHVMUktX8ZqhdCeZ9jK6glzGMhjt/zBrlIFpGjk8vh+tlSl/qlwYJIoSJqZtEq3EvvpAqmlHENfytb3iVPjNB0aPoX1V5GNwhri5tX+7M2XcpNAnU7u8zvEwCGL2j/uIqapxjWhqQNUVygzO4brb1gahvUEN+cVZnuuF6/lsGkbqUv5EcFanGkYTDZk2TdbnT6extxco8wu5QYxzewqrL+haxTWo/z89q6z/bYLmVG1z7klX5GRqAlaqdF647TkOVO10msR5Drt3wC49ffeDOMapebdJpxzCL1ZSpPv01alxOg077Eag8rZ52iaCsWoib+vlIx5Nunu7fr9jmFYn2ZppzSopu2zDvvD8rxcJHE/aSy5iglst1Vic/BqnqItWhsUUJqqWBvWD6BhWJ+k5ub3yZibze616pi+5vf+zSKGsjMatV5LZqjWJX1AgBxVSEaDRR+dSZCE07TD/iUWcw3DepQhfX9l4/Dmfr/ZnZbGTG6+aFx6ilo0Y9AB7UpDVRZqOCGy1tNuyd7bgbx6Oh5G9Sghr0Sv0htp7zKNvN50byhLw8X2yS+0NaTgyBAkwsjOnqeJG9YWHNRacLrMy1pc3xcO4xqj5/6w1/HEn0GQWvfAoZ/qGlIGx0VVVmslVY9aKySj06fHtcyWfdDqjcZhWI/y00914u324hVv+ec358IlywdW8hBi8DnY7KIYtlopGYo1WkX12SRPoW/vncaOR1q/yTQK61PU3DySlI+LY6egSViSSlCQ4NW+c1IHm41anOhN0kj2LsEsdkxcP3ZGYT1K0LYvuN/0EdXXUy6Nmb5DN1AxZBC0ZhJ2z6JKQh+OC1oBvP4XHMaZtvGrn7gyDOujlEz2LC2MEq0AXFOrAogxhorYT6IC55ljVXEVkpZL8tMosQm0aK9OyiiwR0m50/x72PBWEf+6EX1yBMR5M/oHPH26ReNjpWZE+vYpl1w0KjmLYSM+GU7GxywmSJvy5BLR6pV8GNejNO32h7u3JPVe7z/4sJgWNv1UxMhGn4Y6F8zFxeaqN1ndsGvNq7lzYWaqAq6ehYdhPcrKa6Wk9gLO58x73vH1zwd56KGkpapH0VKeQm+QQK79VDvxIZIPVURyMjEFHfuQMXGDmTAOZnVhPAzrcZ7OBvNiOne4MCFzlgrknWqFjKDBqg+NvMem1iVj6If9V09tuqwV0vrTZcOwHqdl97BMBQsTZRFV4zY1E2wFlVdq49x5syo5Rn0qYbqN3K+/MW4Y1aMcvP/msrhWQ8g2pd5+j5ideK8SwWZDmDL2lWKhxNRXPswaWX79LugwrhkvJzkubIkjRPViVdW0V8nklPHSz7RnMK6wC4jZGNXd67fEh4F8eMNXbfPz6eGwcPZULQR728Q6EfJZc3mDaNG57tdtxYbJoPHr/5qBYSCfuPP3s8GTd5+8Sp6QPXotWJqIgvGq/ip4VT6af6ymon5m4fpzx8NAnrh7NTXngnp5e1q6Q1ZyFMsErur10WI/3p/FlJaoFSCrI40jzI4WiOur9VFUT/HymawENqZmp6oPyRsvLWipahGkqi4urjcrIBNMJZddf8/oMKrHWHn45ZdFY0SSJthMhgo1H/qeVDT9VwFVz4U92ZqKfpLXX5E2DOQjdz252P1+uylvLs9nZfYfuLz7x3FRXKh1Tr45yKWGqH5APJq+f5u9SriUikUvxaXZ7yvyafXp9GFYwxQtJcZZVTCcqRrrVdJEBcLVetfnn1TeGtK87stsytB9AZE5DOsRYvq/N79d7Oa3Rc7nr/VfebXUnzD03Tn9/EnWumahnI9NScEG9pz1T1AvKX52fp/7ApsmhnF9lKS3J0DevLP/N+cTID+fp6qmMquXDKaQuOL6Mtxagk2OMqKRbL1Fnmp1MusfdzQM62M0LZwFeuJIKBP7VjC0QaLkXJjRFoMoGVhHeu6/fQaMn5JkIcDqrcdhXB9jabs53fRW281HWm1P5KEKaLCqh9LHZRxRca20WhJUsUkwq5iq3oaZnPkChz8O4/oYLe/6JTe/90tuzv2Sm8/ul/Tl7Oo7VFXlrjVJjTc4UnkRWuJiKrCXTGWajxyuv9tiGNa//6/fm2aaorxUBdR4e5R//wfWqRbN')))


def fixture_tree(leaves):
    """Create immutable Git tree records without writing a candidate checkout."""
    entries = {path: {"path": path, "mode": mode, "type": "blob", "sha": oid}
               for path, (mode, oid) in leaves.items()}
    directories = {str(parent) for path in leaves for parent in Path(path).parents if str(parent) != "."}
    for directory in sorted(directories | {""}, key=lambda path: path.count("/") + bool(path), reverse=True):
        children = [item for path, item in entries.items() if path.rpartition("/")[0] == directory]
        payload = b""
        for item in sorted(children, key=lambda item: (item["path"].rpartition("/")[2] +
                           ("/" if item["type"] == "tree" else "")).encode()):
            payload += item["mode"].lstrip("0").encode() + b" " + item["path"].rpartition("/")[2].encode()
            payload += b"\0" + bytes.fromhex(item["sha"])
        oid = hashlib.sha1(b"tree " + str(len(payload)).encode() + b"\0" + payload).hexdigest()
        if directory:
            entries[directory] = {"path": directory, "mode": "040000", "type": "tree", "sha": oid}
    return {"sha": oid, "truncated": False, "tree": list(entries.values())}


class DevtoolsBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.descriptor = json.loads((ROOT / ".lit/devtools-first-policy.json").read_bytes())
        self.descriptor["shared_source"].update(accepted_sha="e" * 40, status="accepted-protected-source")
        self.base = self.descriptor["develop"]["sha"]
        self.repository = bootstrap.REPOSITORY
        leaves = {item["path"]: (item["mode"], item["sha"]) for item in BASE_TREE["tree"]
                  if item["type"] == "blob"}
        # Construct independently from the checked Source data, not from the
        # bootstrap expected_tree implementation under test.
        for change in self.descriptor["changes"]:
            path = change["path"]
            if change["operation"] == "delete":
                del leaves[path]
            elif "after" in change:
                leaves[path] = (change["after"]["mode"], change["after"]["blob"])
            else:
                payload = self.descriptor["adapter_template"].replace("__DEFINING_COMMON_SHA__", SOURCE).encode()
                leaves[path] = ("100644", hashlib.sha1(b"blob " + str(len(payload)).encode() + b"\0" + payload).hexdigest())
        self.head_tree = fixture_tree(leaves)
        self.pull = {"number": 3, "state": "open", "draft": False, "title": "Native policy", "body": "", "labels": [],
                     "user": {"login": "litroc", "id": 76040632, "type": "User"},
                     "base": {"sha": self.base, "ref": "develop", "repo": {"full_name": self.repository, "id": bootstrap.REPOSITORY_ID}},
                     "head": {"sha": HEAD, "ref": "feature", "repo": {"full_name": self.repository, "id": bootstrap.REPOSITORY_ID}}}
        self.records = {self.base: {"sha": self.base, "tree": {"sha": BASE_TREE["sha"]},
                        "parents": [{"sha": oid} for oid in self.descriptor["historical_metadata_graph"][1]["parents"]]},
                        HEAD: {"sha": HEAD, "tree": {"sha": self.head_tree["sha"]}, "parents": [{"sha": self.base}]}}
        for record in [self.descriptor["main"], *self.descriptor["historical_metadata_graph"]]:
            self.records[record["sha"]] = {"sha": record["sha"], "tree": {"sha": record["tree"]},
                                           "parents": [{"sha": oid} for oid in record["parents"]]}
        self.api = Mock()
        self.api.call.side_effect = self.call
        self.api.file.side_effect = control.ControlError("base policy is genuinely absent")
        self.source = patch.object(bootstrap, "descriptor", return_value=self.descriptor)
        self.source.start()
        self.addCleanup(self.source.stop)

    def call(self, path, **kwargs):
        self.assertNotIn("method", kwargs)  # no effect is permitted in bootstrap
        prefix = f"repos/{self.repository}"
        if path == prefix:
            return {"full_name": self.repository, "id": bootstrap.REPOSITORY_ID}
        if path.startswith(prefix + "/git/ref/heads/"):
            ref = path.rsplit("/", 1)[1]
            return {"ref": "refs/heads/" + ref,
                    "object": {"sha": self.descriptor[ref]["sha"]}}
        if path.startswith(prefix + "/git/commits/"):
            return copy.deepcopy(self.records[path.rsplit("/", 1)[1]])
        if path.startswith(prefix + "/git/trees/"):
            oid = path.rsplit("/", 1)[1].split("?")[0]
            return copy.deepcopy({BASE_TREE["sha"]: BASE_TREE, MAIN_TREE["sha"]: MAIN_TREE,
                                  self.head_tree["sha"]: self.head_tree}[oid])
        if path == prefix + "/actions/runs/10":
            return {"workflow_id": 77, "path": control.WORKFLOW,
                    "workflow_url": prefix.replace("repos/", "https://api.github.com/repos/") +
                    "/actions/required_workflows/77"}
        if path == prefix + "/pulls/3":
            return copy.deepcopy(self.pull)
        raise AssertionError(path)

    def policy(self):
        return control.policy(self.api, self.repository, self.pull["base"]["sha"], SOURCE, pull=self.pull)

    def test_real_policy_entry_accepts_only_complete_source_owned_first_delta(self):
        result = self.policy()
        self.assertEqual(self.descriptor["policy"]["quality"], result["quality"])
        self.assertIs(True, result["artifact_publication"])
        self.api.file.assert_not_called()
        self.assertEqual("copilot", control.classify(self.pull, self.repository))

    def test_exact_eighteenth_fixture_is_required_for_human_main_and_preparation(self):
        self.assertEqual(18, len(self.descriptor["changes"]))
        self.assertEqual(18, len({entry["path"] for entry in self.descriptor["changes"]}))
        fixture = "tests/test_lit_push_ready.py"
        record = next(entry for entry in self.descriptor["changes"] if entry["path"] == fixture)
        self.assertEqual({"mode": "100644", "blob": "3d2707da21ada0388c3fcfdc92de19e7b2dad415"}, record["before"])
        self.assertEqual({"mode": "100644", "blob": "75e6d35a1783ceb0c2d1f0a1e15ca6544627ff8d",
                          "sha256": "437d12bb29adf10f6b62b49153165d68bb00c395c1a66497ca1deadb1f6d4dbc"},
                         record["after"])
        original_pull, original_tree = copy.deepcopy(self.pull), copy.deepcopy(self.head_tree)
        leaves = {entry["path"]: (entry["mode"], entry["sha"])
                  for entry in original_tree["tree"] if entry["type"] == "blob"}
        for route in ("human", "main", "prepare"):
            self.pull = copy.deepcopy(original_pull)
            self.head_tree = copy.deepcopy(original_tree)
            self.records[HEAD]["tree"]["sha"] = self.head_tree["sha"]
            if route != "human":
                self.pull["base"].update(sha=self.descriptor["main"]["sha"], ref="main")
                self.pull["head"]["ref"] = "develop"
                self.pull["user"] = dict(zip(("login", "id", "type"), control.RELEASE))
            planned = {"base": {"sha": self.descriptor["main"]["sha"]}, "head": {"sha": HEAD}}
            preparation = bootstrap.preparation_policy(self.api, self.repository, SOURCE) if route == "prepare" else None
            def validate():
                if preparation is not None:
                    return bootstrap.promotion_context(self.api, self.repository, planned, preparation)
                return self.policy()
            validate()  # all three real readers require and accept the complete eighteen-path tree
            defects = {
                "old-seventeen": (fixture, ("100644", record["before"]["blob"])),
                "missing": (fixture, None),
                "foreign-blob": (fixture, ("100644", "f" * 40)),
                "wrong-mode": (fixture, ("100755", record["after"]["blob"])),
                "extra": ("foreign", ("100644", "f" * 40)),
            }
            for defect, (path, replacement) in defects.items():
                current = dict(leaves)
                if replacement is None: del current[path]
                else: current[path] = replacement
                self.head_tree = fixture_tree(current)
                self.records[HEAD]["tree"]["sha"] = self.head_tree["sha"]
                with self.subTest(route=route, defect=defect), \
                        self.assertRaisesRegex(control.ControlError, "exact-eighteen"):
                    validate()
        self.pull, self.head_tree = original_pull, original_tree

    def test_real_common_quality_prepare_validates_delta_before_base_metadata(self):
        self.api.file.side_effect = None
        self.api.file.return_value = b"schema_version: 1\nrepository: container-ee-wunder-devtools-ubi9\nrepository_type: container_image\n"
        env = {"GITHUB_REPOSITORY": self.repository, "GITHUB_RUN_ID": "10", "NATIVE_PULL_NUMBER": "3",
               "NATIVE_HEAD": HEAD, "NATIVE_BASE": self.base,
               "NATIVE_JOB": json.dumps({"workflow_repository": control.SOURCE,
                    "workflow_file_path": control.WORKFLOW, "workflow_sha": SOURCE, "check_run_id": 1})}
        result = quality.prepare(self.api, env)
        self.assertEqual("container_image", result["repository_type"])
        self.api.file.assert_called_once_with(self.repository, ".lit/repository.yml", self.base)

    def test_extra_missing_foreign_policy_mode_and_inventory_all_fail_before_effects(self):
        original = copy.deepcopy(self.head_tree)
        leaves = {item["path"]: (item["mode"], item["sha"]) for item in original["tree"] if item["type"] == "blob"}
        for path, change in (("foreign", ("100644", "f" * 40)), ("AGENTS.md", None),
                             (bootstrap.POLICY, ("100644", "f" * 40)),
                             ("AGENTS.md", ("100755", leaves["AGENTS.md"][1])),
                             (".github/workflows/delivery-operations.yml", ("100644", "f" * 40)),
                             (".github/workflows/copilot-review.yml", ("100644", "ec0c9b4bae4b946cc379bded81f6bc6a773886f0")),
                             (".lit/managed-assets.json", ("100644", "f" * 40))):
            with self.subTest(path=path, change=change):
                current = dict(leaves)
                if change is None: del current[path]
                else: current[path] = change
                self.head_tree = fixture_tree(current)
                self.records[HEAD]["tree"]["sha"] = self.head_tree["sha"]
                with self.assertRaisesRegex(control.ControlError, "exact-eighteen"):
                    self.policy()
        self.head_tree = original

    def test_complete_tree_detects_truncation_omission_duplicate_and_symlink(self):
        for mutate in (lambda value: value.update(truncated=True),
                       lambda value: value["tree"].pop(),
                       lambda value: value["tree"].append(value["tree"][0]),
                       lambda value: value["tree"][0].update(mode="120000", type="blob")):
            value = copy.deepcopy(BASE_TREE)
            mutate(value)
            with self.subTest(mutate=mutate), patch.object(self.api, "call", return_value=value), \
                    self.assertRaises(control.ControlError):
                bootstrap.tree(self.api, BASE_TREE["sha"])

    def test_foreign_author_fork_base_repo_id_and_absent_context_deny(self):
        for mutate in (lambda: self.pull["user"].update(login="other"),
                       lambda: self.pull["head"]["repo"].update(full_name="foreign/repo"),
                       lambda: self.pull["head"]["repo"].update(id=2),
                       lambda: self.pull["base"].update(sha="f" * 40)):
            old = copy.deepcopy(self.pull)
            mutate()
            with self.subTest(mutate=mutate), self.assertRaises((control.ControlError, KeyError)):
                self.policy()
            self.pull = old
        with self.assertRaisesRegex(control.ControlError, "pull-context"):
            control.policy(self.api, self.repository, self.base, SOURCE)
        with patch.object(self.api, "call", return_value={"full_name": self.repository, "id": 1}), \
                self.assertRaisesRegex(control.ControlError, "repository-identity"):
            self.policy()

    def test_pending_real_source_and_unknown_api_are_not_absence_authority(self):
        self.source.stop()
        # Explicit fixtures survive a legitimate later pin in the real local
        # descriptor. Exercise its actual reader, not the descriptor() mock.
        accepted = Mock()
        accepted.read_bytes.return_value = json.dumps(self.descriptor).encode()
        pending_value = copy.deepcopy(self.descriptor)
        pending_value["shared_source"].update(accepted_sha=None, status="blocked-until-protected-source-acceptance")
        pending = Mock()
        pending.read_bytes.return_value = json.dumps(pending_value).encode()
        with patch.object(bootstrap, "DESCRIPTOR", accepted):
            self.assertEqual("e" * 40, bootstrap.descriptor()["shared_source"]["accepted_sha"])
            with patch.object(bootstrap, "DESCRIPTOR", pending), \
                    self.assertRaisesRegex(control.ControlError, "shared-source-not-accepted"):
                self.policy()
        with patch.object(self.api, "call", side_effect=control.ControlError("native-api-unavailable")), \
                self.assertRaisesRegex(control.ControlError, "native-api-unavailable"):
            self.policy()

    def test_first_main_exact_baseline_is_honest_and_consumer_flag_cannot_create_context(self):
        self.pull["base"].update(sha=self.descriptor["main"]["sha"], ref="main")
        self.pull["head"]["ref"] = "develop"
        self.pull["user"] = dict(zip(("login", "id", "type"), control.RELEASE))
        result = self.policy()
        self.assertIsInstance(result["_devtools_first_policy"], bootstrap.FirstPolicy)
        self.assertIsNone(bootstrap.promotion_context(self.api, self.repository, self.pull,
                                                   {"_devtools_first_policy": {"source": SOURCE}}))
        self.records[self.base]["parents"].reverse()
        with self.assertRaisesRegex(control.ControlError, "historical-graph-drift"):
            self.policy()

    def test_typed_preparation_read_retains_lineage_but_grants_no_tree_acceptance(self):
        result = bootstrap.preparation_policy(self.api, self.repository, SOURCE)
        self.assertIn(SOURCE, result["accepted_sources"])
        self.assertIsNone(result["_devtools_first_policy"].head)
        self.assertEqual("prepare", result["_devtools_first_policy"].purpose)
        with self.assertRaisesRegex(control.ControlError, "preparation-target"):
            bootstrap.preparation_policy(self.api, "lightning-it/other", SOURCE)

    def test_previously_accepted_sources_are_retained_before_actual_main678(self):
        entries = json.loads((ROOT / ".lit/workflow-source-lineage.json").read_bytes())["accepted_predecessors"]
        self.assertEqual([
            "7215c32d9cc957e560110493d0d94cba14c8287b", "31cbb39db553a04c3b7badb53b2bcf18d88293d1",
            "b815cefb4a5f18cd97b3947c789b6db59fedf991", "6ae02b7b44e9a6a8708dd4e9e75f9491d0b472a4",
            "6845abfda6069e33b3939736c88177dabc9bf315", "8a96861b663a994a6dfd77ced2e984f65cc7d436",
            "6c569721323d24cabad43f8caa162be60a7afdcb", "f1bd4951288b1ce52a6cb30ab6432e201cf45507",
            "bb1a5df9f54c5f98547048297e7e367cc382543e",
        ], entries[:9])
        self.assertEqual("678560bdd02d32ccae59c430f0047f85a81ec72e", entries[9])
        self.assertEqual("4f12f255b4375907967d87a5462cc99930c5f3c7", entries[10])

    def test_installed_policy_keeps_ordinary_reader_and_api_failures_never_fallback(self):
        leaves = {entry["path"]: (entry["mode"], entry["sha"])
                  for entry in BASE_TREE["tree"] if entry["type"] == "blob"}
        leaves[bootstrap.POLICY] = ("100644", "a" * 40)
        installed = fixture_tree(leaves)
        def call(path, **kwargs):
            if "/git/trees/" in path:
                return installed
            if "/git/commits/" in path:
                return {"sha": self.base, "tree": {"sha": installed["sha"]}, "parents": []}
            return self.call(path, **kwargs)
        self.api.file.side_effect = None
        self.api.file.return_value = json.dumps(self.descriptor["policy"]).encode()
        with patch.object(self.api, "call", side_effect=call):
            self.assertNotIn("_devtools_first_policy", self.policy())
        self.api.file.assert_called_once_with(self.repository, bootstrap.POLICY, self.base)

    def test_later_installed_base_uses_only_normal_reader_and_missing_policy_is_not_admitted(self):
        later = "f" * 40
        self.pull["base"]["sha"] = later
        self.api.call.side_effect = AssertionError("ordinary policy must not inspect bootstrap trees")
        self.api.file.side_effect = None
        self.api.file.return_value = json.dumps(self.descriptor["policy"]).encode()
        self.assertNotIn("_devtools_first_policy", self.policy())
        self.api.file.assert_called_once_with(self.repository, bootstrap.POLICY, later)
        self.api.call.assert_not_called()
        self.api.file.side_effect = control.ControlError("ordinary-policy-unavailable")
        with self.assertRaisesRegex(control.ControlError, "ordinary-policy-unavailable"):
            self.policy()
        self.api.call.assert_not_called()

    def test_actual_promotion_ingress_checks_new_merge_and_reports_metadata_baseline(self):
        import workflow_subject
        self.pull["base"].update(sha=self.descriptor["main"]["sha"], ref="main")
        self.pull["head"]["ref"] = "develop"
        self.pull["user"] = dict(zip(("login", "id", "type"), control.RELEASE))
        config = self.policy()
        api_call = self.call
        ingress = {"number": 8, "merged_at": "2026-10-18T00:00:00Z", "merge_commit_sha": HEAD,
                   "base": {"ref": "develop"}}
        self.api.call.side_effect = lambda path, **kw: ingress if path.endswith("/pulls/8") else api_call(path, **kw)
        self.api.pages.return_value = [ingress]
        def git(objects, *arguments, **kwargs):
            if arguments[0] == "merge-base": return arguments[2]
            if arguments[0] == "rev-list": return self.base + "\n" + HEAD
            if arguments[0] == "merge-tree": return self.head_tree["sha"]
            if arguments[0] == "diff": return b"fixture complete reviewed delta"
            raise AssertionError(arguments)
        with patch.object(workflow_subject, "fetch_objects"), patch.object(workflow_subject, "git", side_effect=git), \
                patch.object(control.subprocess, "run", return_value=Mock(returncode=0)), \
                patch.object(control, "check_native_control", return_value={"route": "copilot"}) as native:
            result = control.promotion_ingress(self.api, self.repository, self.pull, config)
            native.assert_called_once_with(self.api, self.repository, ingress, config)
            self.assertEqual([HEAD], [item["merge"] for item in result["ingress"]])
            self.assertEqual(self.descriptor["historical_metadata_graph"],
                             result["pre_admission_metadata_baseline"]["historical_graph"])
            planned = {"base": {"sha": self.descriptor["main"]["sha"]}, "head": {"sha": HEAD}}
            preparation = bootstrap.preparation_policy(self.api, self.repository, SOURCE)
            planned_result = control.promotion_ingress(self.api, self.repository, planned, preparation)
            self.assertEqual(result, planned_result)
            self.assertEqual(2, native.call_count)
            with self.assertRaisesRegex(control.ControlError, "native-promotion-context"):
                control.promotion_ingress(self.api, self.repository, planned, config)
            with self.assertRaisesRegex(control.ControlError, "planned-promotion-shape"):
                control.promotion_ingress(self.api, self.repository, self.pull, preparation)
            self.descriptor["shared_source"]["accepted_sha"] = "f" * 40
            with self.assertRaisesRegex(control.ControlError, "descriptor-drift"):
                control.promotion_ingress(self.api, self.repository, planned, preparation)
            self.descriptor["shared_source"]["accepted_sha"] = "e" * 40
            self.api.pages.return_value = []
            with self.assertRaisesRegex(control.ControlError, "unattributed-ingress"):
                control.promotion_ingress(self.api, self.repository, self.pull, config)
            self.api.pages.return_value = [ingress]
            native.side_effect = control.ControlError("native-acceptance-missing")
            with self.assertRaisesRegex(control.ControlError, "native-acceptance-missing"):
                control.promotion_ingress(self.api, self.repository, self.pull, config)


if __name__ == "__main__":
    unittest.main()
