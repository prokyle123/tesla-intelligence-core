from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import torch
from torch import nn

# Keep the Pi responsive during training/inference. Users can override this via env.
_THREADS = max(1, min(int(os.environ.get('GHOST_TORCH_THREADS', '4')), os.cpu_count() or 4))
torch.set_num_threads(_THREADS)
try:
    torch.set_num_interop_threads(1)
except RuntimeError:
    pass


class TemporalGRU(nn.Module):
    """Small CPU-friendly recurrent model for Tesla telemetry windows."""
    def __init__(self, input_size: int, hidden_size: int = 64, layers: int = 2,
                 dropout: float = 0.12, output_size: int = 5):
        super().__init__()
        self.gru = nn.GRU(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=layers,
            dropout=dropout if layers > 1 else 0.0,
            batch_first=True,
        )
        self.norm = nn.LayerNorm(hidden_size)
        self.head = nn.Sequential(
            nn.Linear(hidden_size, 48),
            nn.SiLU(),
            nn.Dropout(dropout),
            nn.Linear(48, output_size),
        )

    def forward(self, x):
        y, _ = self.gru(x)
        z = self.norm(y[:, -1, :])
        return self.head(z)

    def forward_diagnostics(self, x):
        """Return the normal prediction plus read-only tensors used by the local observatory.

        No parameters, weights or forward behavior are changed. The diagnostics are
        derived from the exact same inference pass that produces the forecast.
        """
        y, h = self.gru(x)
        last = y[:, -1, :]
        z = self.norm(last)
        dense_pre = self.head[0](z)
        dense_act = self.head[1](dense_pre)
        dense_drop = self.head[2](dense_act)
        out = self.head[3](dense_drop)
        return out, {
            'gru_output': y,
            'hidden_final': h,
            'last_state': last,
            'latent': z,
            'dense_pre': dense_pre,
            'dense_activation': dense_act,
        }


@dataclass
class TorchGRUBackend:
    input_size: int
    output_size: int
    hidden_size: int = 64
    layers: int = 2
    dropout: float = 0.12

    name: str = 'torch_gru_multitask'

    def create(self) -> TemporalGRU:
        return TemporalGRU(
            self.input_size,
            hidden_size=self.hidden_size,
            layers=self.layers,
            dropout=self.dropout,
            output_size=self.output_size,
        )

    @staticmethod
    def save(path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        torch.save(payload, str(path))

    @staticmethod
    def load(path: Path | str) -> dict:
        # weights_only=False is required because the artifact intentionally stores
        # scaler metadata and plain Python dictionaries beside the state_dict.
        return torch.load(str(path), map_location='cpu', weights_only=False)
