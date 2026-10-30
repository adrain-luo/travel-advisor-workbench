"""Check pinned offline OCR resources and Chinese export font without network access."""
from pathlib import Path
import hashlib
import importlib.metadata
import json
import sys

EXPECTED = {
    'ch_ppocr_mobile_v2.0_cls_mobile.onnx': 'e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c',
    'PP-OCRv6_det_small.onnx': '090f04abcd9d9a7498bc4ebf677e4cb9bdce1fe4197ddb7e529f1ef44e1ff94f',
    'PP-OCRv6_rec_small.onnx': '6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884',
}

def main():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    distribution = importlib.metadata.distribution('rapidocr')
    if distribution.version != '3.9.2':
        raise ValueError('RAPIDOCR_VERSION_MISMATCH')
    for name, expected in EXPECTED.items():
        path = Path(distribution.locate_file('rapidocr/models/' + name))
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('OCR_RESOURCE_HASH_MISMATCH: ' + name)
    from backend.exports import _font
    font = _font(22)
    print(json.dumps({'status': 'ok', 'rapidocr': distribution.version, 'model_count': len(EXPECTED),
                      'chinese_font': Path(font.path).name}, ensure_ascii=False))

if __name__ == '__main__':
    main()
