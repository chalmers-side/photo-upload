"""Minimal CLIP BPE tokenizer (OpenAI CLIP, MIT). Vocab downloads on first use."""
import gzip
import re
import urllib.request
from functools import lru_cache
from pathlib import Path

from config import appsetting

BPE_URL = "https://openaipublic.azureedge.net/clip/bpe_simple_vocab_16e6.txt.gz"
_SPLIT = re.compile(r"'s|'t|'re|'ve|'m|'ll|'d|[A-Za-z]+|[0-9]+|[^A-Za-z0-9\s]+", re.I)


@lru_cache()
def bytes_to_unicode():
    bs = list(range(ord("!"), ord("~") + 1))
    bs += list(range(ord("¡"), ord("¬") + 1))
    bs += list(range(ord("®"), ord("ÿ") + 1))
    cs = bs[:]
    n = 0
    for b in range(256):
        if b not in bs:
            bs.append(b)
            cs.append(256 + n)
            n += 1
    return dict(zip(bs, (chr(c) for c in cs)))


def get_pairs(word):
    pairs = set()
    prev = word[0]
    for ch in word[1:]:
        pairs.add((prev, ch))
        prev = ch
    return pairs


def _bpe_path():
    path = Path(appsetting.judge_model_dir) / "bpe_simple_vocab_16e6.txt.gz"
    if path.is_file() and path.stat().st_size > 1000:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(BPE_URL, headers={"User-Agent": "photo-upload-judge"})
    with urllib.request.urlopen(req, timeout=60) as src, path.open("wb") as out:
        out.write(src.read())
    return path


class Tokenizer:
    def __init__(self):
        self.byte_encoder = bytes_to_unicode()
        merges = gzip.open(_bpe_path()).read().decode("utf-8").split("\n")
        merges = merges[1 : 49152 - 256 - 2 + 1]
        merges = [tuple(m.split()) for m in merges]
        vocab = list(bytes_to_unicode().values())
        vocab = vocab + [v + "</w>" for v in vocab]
        for merge in merges:
            vocab.append("".join(merge))
        vocab.extend(["<|startoftext|>", "<|endoftext|>"])
        self.encoder = dict(zip(vocab, range(len(vocab))))
        self.bpe_ranks = dict(zip(merges, range(len(merges))))
        self.cache = {
            "<|startoftext|>": "<|startoftext|>",
            "<|endoftext|>": "<|endoftext|>",
        }

    def bpe(self, token):
        if token in self.cache:
            return self.cache[token]
        word = tuple(token[:-1]) + (token[-1] + "</w>",)
        pairs = get_pairs(word)
        if not pairs:
            return token + "</w>"
        while True:
            bigram = min(pairs, key=lambda p: self.bpe_ranks.get(p, float("inf")))
            if bigram not in self.bpe_ranks:
                break
            first, second = bigram
            new_word = []
            i = 0
            while i < len(word):
                try:
                    j = word.index(first, i)
                    new_word.extend(word[i:j])
                    i = j
                except ValueError:
                    new_word.extend(word[i:])
                    break
                if word[i] == first and i < len(word) - 1 and word[i + 1] == second:
                    new_word.append(first + second)
                    i += 2
                else:
                    new_word.append(word[i])
                    i += 1
            word = tuple(new_word)
            if len(word) == 1:
                break
            pairs = get_pairs(word)
        word = " ".join(word)
        self.cache[token] = word
        return word

    def encode(self, text, context_length=77):
        sot = self.encoder["<|startoftext|>"]
        eot = self.encoder["<|endoftext|>"]
        tokens = [sot]
        for token in _SPLIT.findall(text.lower()):
            token = "".join(self.byte_encoder[b] for b in token.encode("utf-8"))
            tokens.extend(self.encoder[bpe] for bpe in self.bpe(token).split(" "))
        tokens.append(eot)
        tokens = tokens[:context_length]
        out = [0] * context_length
        out[: len(tokens)] = tokens
        return out
