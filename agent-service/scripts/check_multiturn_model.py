import asyncio
from pathlib import Path

from app.core.config import Settings
from app.evaluation.multiturn import (
    dump_evaluation_value,
    evaluate_create_output,
    evaluate_update_output,
    load_multiturn_dataset,
)
from app.services.parser_factory import (
    create_task_parser,
    create_task_update_parser,
)
from app.services.task_draft_clarification import format_task_collection_input
from app.services.task_update_clarification import (
    format_task_update_collection_input,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DATASET_PATH = (
    REPOSITORY_ROOT / 'evaluation' / 'datasets' / 'multiturn_cases.v1.json'
)


async def main() -> int:
    settings = Settings()
    if not settings.llm_api_key:
        print('LLM_API_KEY 未配置，未调用真实模型。')
        return 2

    dataset = load_multiturn_dataset(DATASET_PATH)
    create_parser = create_task_parser(settings)
    update_parser = create_task_update_parser(settings)
    passed_turns = 0
    total_turns = sum(len(case.messages) for case in dataset.cases)

    for case in dataset.cases:
        collected: list[str] = []
        print(f'\n[{case.id}] {case.kind}')
        for turn, (message, expected) in enumerate(
            zip(case.messages, case.expected, strict=True),
            start=1,
        ):
            collected.append(message)
            try:
                if case.kind == 'create_task':
                    output = await create_parser.parse(
                        format_task_collection_input(collected),
                        timezone=case.timezone,
                    )
                    failures = evaluate_create_output(output, expected)
                else:
                    output = await update_parser.parse(
                        format_task_update_collection_input(collected),
                        current_task=case.current_task,
                        timezone=case.timezone,
                        current_datetime=case.current_datetime,
                    )
                    failures = evaluate_update_output(output, expected)
            except Exception as exc:
                output = {'error': f'{type(exc).__name__}: {exc}'}
                failures = ['parser raised an exception']

            ok = not failures
            passed_turns += int(ok)
            result = 'PASS' if ok else 'FAIL'
            details = '' if ok else f' failures={failures}'
            print(
                f'  turn={turn} {result}{details} '
                f'actual={dump_evaluation_value(output)}'
            )

    print(
        f'\n数据集版本 {dataset.version}，通过 '
        f'{passed_turns}/{total_turns} 轮'
    )
    return 0 if passed_turns == total_turns else 1


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
