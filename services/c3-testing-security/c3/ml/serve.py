"""The trained model, in its own process, answering one method at a time.

The process boundary is the point. Torch and transformers are around two
gigabytes of wheels, this machine has under six of memory, and the orchestrator
has to keep running while a model is loaded. Importing them into the workspace
would put that weight into CI and into every developer's environment for the
sake of one arm of one comparison.

It is also the honest shape. The trained arm's claim is that it runs offline,
locally, with no API call and no per token cost, and a thing that can be
started as its own process on a machine with no network is that claim made
concrete rather than asserted.

The protocol is newline delimited JSON on stdin and stdout, because it is the
one protocol that needs no port, no dependency and no shutdown handshake: when
the parent closes the pipe the child ends. One request object per line:

    {"methods": ["public void bad() { ... }", ...]}

and one response object per line, in the same order:

    {"predictions": [{"vulnerable": true, "cwe": "CWE-89", "score": 0.97}, ...]}

Anything that goes wrong answers `{"error": "..."}` on the same line rather
than dying, so the arm reports a failure instead of a silence.
"""

import argparse
import json
import sys
from pathlib import Path

MAX_TOKENS = 512
BASE_MODEL = "microsoft/graphcodebert-base"


def build(model_dir: Path):
    """Load the weights and the labels they are meaningless without.

    Everything comes out of the model directory, including the tokenizer and
    the encoder's configuration. The encoder is built from that configuration
    rather than downloaded, because its trained weights are in the state dict
    anyway and fetching the pretrained ones would be both wasteful and a lie:
    this arm's claim is that it runs with the network unplugged, and an
    artefact that phones home on first use does not.
    """
    import torch
    from torch import nn
    from transformers import AutoConfig, AutoModel, AutoTokenizer

    labels = json.loads((model_dir / "labels.json").read_text())
    classes = list(labels["classes"])
    source = str(model_dir) if (model_dir / "config.json").is_file() else BASE_MODEL
    tokenizer = AutoTokenizer.from_pretrained(source)
    encoder = AutoModel.from_config(AutoConfig.from_pretrained(source))

    class TwoHeads(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.encoder = encoder
            width = encoder.config.hidden_size
            self.dropout = nn.Dropout(0.1)
            self.binary = nn.Linear(width, 2)
            self.cwe = nn.Linear(width, len(classes))

        def forward(self, **encoded):
            pooled = self.dropout(self.encoder(**encoded).last_hidden_state[:, 0])
            return self.binary(pooled), self.cwe(pooled)

    model = TwoHeads()
    model.load_state_dict(torch.load(model_dir / "weights.pt", map_location="cpu"))
    model.eval()
    return torch, tokenizer, model, classes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, help="the directory Colab produced")
    arguments = parser.parse_args()
    model_dir = Path(arguments.model)

    try:
        torch, tokenizer, model, classes = build(model_dir)
    except Exception as error:
        print(json.dumps({"error": f"{type(error).__name__}: {error}"}), flush=True)
        return
    print(json.dumps({"ready": True, "classes": len(classes)}), flush=True)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            methods = json.loads(line)["methods"]
            encoded = tokenizer(
                methods, truncation=True, padding=True, max_length=MAX_TOKENS, return_tensors="pt"
            )
            with torch.no_grad():
                binary, cwe = model(**encoded)
                confidence = torch.softmax(binary, dim=1)[:, 1]
                verdict = binary.argmax(dim=1)
                classified = cwe.argmax(dim=1)
            answer = {
                "predictions": [
                    {
                        "vulnerable": bool(verdict[index] == 1),
                        "cwe": classes[int(classified[index])],
                        "score": float(confidence[index]),
                    }
                    for index in range(len(methods))
                ]
            }
        except Exception as error:
            answer = {"error": f"{type(error).__name__}: {error}"}
        print(json.dumps(answer), flush=True)


if __name__ == "__main__":
    main()
