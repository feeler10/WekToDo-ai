import asyncio
import json
from pathlib import Path

from app.core.config import Settings
from app.intent.factory import create_intent_service
from app.intent.models import IntentRecognitionContext

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DATASET_PATH = REPOSITORY_ROOT / 'evaluation' / 'datasets' / 'intent_cases.json'


async def main() -> int:
    settings = Settings()
    if not settings.llm_api_key:
        print('LLM_API_KEY 未配置，未调用真实模型。')
        return 2

    cases = json.loads(DATASET_PATH.read_text(encoding='utf-8'))
    service = create_intent_service(settings)
    passed = 0
    for index, case in enumerate(cases, start=1):
        result = await service.recognize(
            IntentRecognitionContext(message=case['text'])
        )
        actual = result.model_dump(mode='json')
        checks = [actual['intent'] == case['expected_intent']]
        if 'expected_target_status' in case:
            checks.append(
                actual['target_status'] == case['expected_target_status']
            )
        if 'expected_needs_clarification' in case:
            checks.append(
                actual['needs_clarification']
                == case['expected_needs_clarification']
            )
        ok = all(checks)
        passed += int(ok)
        print(
            f'[{index:02d}] {"PASS" if ok else "FAIL"} '
            f'{case["text"]}: '
            f'{json.dumps(actual, ensure_ascii=False)}'
        )

    print(f'通过 {passed}/{len(cases)}')
    return 0 if passed == len(cases) else 1


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
