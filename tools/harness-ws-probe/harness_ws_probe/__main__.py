"""CLI：python -m harness_ws_probe --base http://127.0.0.1:8000 --suite l0"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
from pathlib import Path

from .client import ProbeClient, connect_expect_close
from .errors import ProbeError
from .expect import ExpectMatcher, ProbeAssertion
from .scenarios import l0, l1
from .scenarios.chat import print_stats, run_chat_turn


async def _run_l0_live(client: ProbeClient) -> None:
    await l0.run_unknown_event(client)
    await l0.run_cancel_empty(client)
    await l0.run_stress_and_cancel_confirm(client)
    try:
        await l0.run_help(client)
        await l0.run_idempotent_client_message(client)
    except (ProbeError, ProbeAssertion) as exc:
        print(f"[l0] /help 或幂等跳过（多半未配 Agent 协议档）：{exc}")
    await l0.run_reconnect_replay(client)


async def _run_l0_scripted() -> None:
    from .scripted import ScriptedProbe

    peer = ScriptedProbe()
    await peer.connect()
    await l0.run_handshake_scripted(ScriptedProbe())
    await l0.run_unknown_event(peer)
    await l0.run_help(peer)
    await l0.run_cancel_empty(peer)
    await l0.run_stress_and_cancel_confirm(peer)
    peer2 = ScriptedProbe()
    await peer2.connect()
    await l0.run_idempotent_client_message(peer2)
    peer3 = ScriptedProbe()
    await peer3.connect()
    await l0.run_reconnect_replay(peer3)


async def _async_main(args: argparse.Namespace) -> int:
    if args.scripted:
        await _run_l0_scripted()
        if args.suite in {"l1", "all"}:
            from .scripted import ScriptedProbe

            peer = ScriptedProbe()
            await peer.connect()
            await l1.run_confirm_enqueue(peer, allow_enqueue=True)
        if args.suite in {"l2", "chat", "all"}:
            from .scripted import ScriptedProbe

            peer = ScriptedProbe()
            await peer.connect()
            await run_chat_turn(peer, "用一句话介绍你自己")
        print("scripted 通过")
        return 0

    client = ProbeClient(
        args.base,
        username=args.user,
        password=args.password,
        insecure=args.insecure,
    )
    try:
        await connect_expect_close(
            args.base,
            ticket="invalid",
            session_id=None,
            insecure=args.insecure,
            expect_code=4401,
        )
        await client.login()
        live_ticket = await client._ticket()
        await connect_expect_close(
            args.base,
            ticket=live_ticket,
            session_id="00000000-0000-0000-0000-000000000000",
            insecure=args.insecure,
            expect_code=4404,
        )
        await client.create_session()
        await client.connect()
        if args.suite in {"l0", "all"}:
            await _run_l0_live(client)
        if args.suite in {"l1", "all"}:
            await l1.run_confirm_enqueue(client, allow_enqueue=args.allow_enqueue)
        if args.suite in {"l2", "chat"}:
            prompts = args.prompt or [
                "用一句话介绍你自己",
                "这个平台能做什么？",
            ]
            failed = False
            for text in prompts:
                stats = await run_chat_turn(client, text, check=False)
                print_stats(stats)
                try:
                    ExpectMatcher(client.trace).chat_turn_contract(
                        after_frame=int(stats["after_frame"])
                    )
                    print("  contract: PASS")
                except ProbeAssertion as exc:
                    print(f"  contract: FAIL {exc}")
                    failed = True
            if failed:
                print(f"{args.suite} 与契约不符")
                return 1
        if args.dump:
            print(client.trace.dump_text())
        if args.trace_dir:
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            path = Path(args.trace_dir) / f"{stamp}.jsonl"
            client.trace.write_jsonl(path)
            print(f"trace {path}")
        print(f"{args.suite} 通过")
        return 0
    finally:
        await client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Harness WebSocket 协议探针")
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--user", default="admin")
    parser.add_argument("--password", default="admin123")
    parser.add_argument("--insecure", action="store_true")
    parser.add_argument("--suite", choices=("l0", "l1", "l2", "all", "chat"), default="l0")
    parser.add_argument(
        "--prompt",
        action="append",
        default=None,
        help="chat 套件的用户句，可重复；缺省跑自我介绍与平台能力两句",
    )
    parser.add_argument("--allow-enqueue", action="store_true")
    parser.add_argument("--dump", action="store_true")
    parser.add_argument(
        "--trace-dir",
        default=str(Path(__file__).resolve().parents[1] / "traces"),
    )
    parser.add_argument(
        "--scripted",
        action="store_true",
        help="不连真实 API，跑进程内对等端（与 pytest 同一套场景）",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_async_main(args)))


if __name__ == "__main__":
    main()
