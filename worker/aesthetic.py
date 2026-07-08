import io
import pathlib

import torch
import torch.nn as nn
import open_clip
from PIL import Image

# LAION "improved-aesthetic-predictor": a small MLP head on top of a normalized CLIP ViT-L/14
# image embedding, predicting a ~1-10 aesthetic score. CLIP + the head both run locally on the GPU.
CLIP_MODEL = "ViT-L-14"
CLIP_PRETRAINED = "openai"
HEAD_WEIGHTS_URL = ("https://github.com/christophschuhmann/improved-aesthetic-predictor/"
                    "raw/main/sac+logos+ava1-l14-linearMSE.pth")
HEAD_WEIGHTS_PATH = pathlib.Path(__file__).parent / "weights" / "sac+logos+ava1-l14-linearMSE.pth"

class _MLP(nn.Module):
    # Exact architecture of the improved-aesthetic-predictor head (so the released weights load).
    def __init__(self, input_size=768):
        super().__init__()
        self.layers = nn.Sequential(
            nn.Linear(input_size, 1024), nn.Dropout(0.2),
            nn.Linear(1024, 128), nn.Dropout(0.2),
            nn.Linear(128, 64), nn.Dropout(0.1),
            nn.Linear(64, 16),
            nn.Linear(16, 1),
        )

    def forward(self, x):
        return self.layers(x)

def _ensure_head_weights():
    # Download the released head weights once (small file) if they're not already cached.
    if not HEAD_WEIGHTS_PATH.exists():
        import requests
        print("Downloading aesthetic head weights…")
        HEAD_WEIGHTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        response = requests.get(HEAD_WEIGHTS_URL, timeout=180)
        response.raise_for_status()
        HEAD_WEIGHTS_PATH.write_bytes(response.content)

    return str(HEAD_WEIGHTS_PATH)


class AestheticScorer:
    def __init__(self, head_weights=None, device=None):
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")

        self.clip, _, self.preprocess = open_clip.create_model_and_transforms(
            CLIP_MODEL, pretrained=CLIP_PRETRAINED)
        self.clip = self.clip.to(self.device).eval()

        self.head = _MLP().to(self.device).eval()
        state = torch.load(head_weights or _ensure_head_weights(), map_location=self.device)
        self.head.load_state_dict(state)

        print(f"Aesthetic scorer ready on {self.device}.")

    @torch.no_grad()
    def score(self, image_bytes):
        # Bytes -> normalized CLIP embedding -> MLP -> a single ~1-10 aesthetic score.
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        tensor = self.preprocess(image).unsqueeze(0).to(self.device)

        embedding = self.clip.encode_image(tensor)
        embedding = embedding / embedding.norm(dim=-1, keepdim=True)

        return float(self.head(embedding.float()).item())
