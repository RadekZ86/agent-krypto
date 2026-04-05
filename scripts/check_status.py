"""Quick check of agent trading status."""
from app.database import SessionLocal
from app.models import Decision, SimulatedTrade, LiveOrderLog, User
from sqlalchemy import select, desc, func

with SessionLocal() as s:
    ds = s.execute(select(Decision).order_by(desc(Decision.timestamp)).limit(5)).scalars().all()
    print("=== LATEST DECISIONS ===")
    for r in ds:
        print(f"  {r.timestamp} {r.symbol} {r.decision} conf={r.confidence:.2f} score={r.score}")

    ots = s.execute(select(SimulatedTrade).where(SimulatedTrade.status == "OPEN")).scalars().all()
    print(f"\n=== OPEN PAPER TRADES: {len(ots)} ===")
    for t in ots:
        print(f"  {t.opened_at} {t.symbol} qty={t.quantity:.6f} buy={t.buy_price:.2f}")

    los = s.execute(select(LiveOrderLog).order_by(desc(LiveOrderLog.created_at)).limit(10)).scalars().all()
    print(f"\n=== LIVE ORDER LOG: {len(los)} ===")
    for r in los:
        detail = (r.detail or "")[:100]
        print(f"  {r.created_at} {r.symbol} {r.action} {r.status} alloc={r.allocation} {detail}")

    u = s.execute(select(User).where(User.username == "radek")).scalar_one_or_none()
    if u:
        print(f"\n=== USER radek ===")
        print(f"  trading_mode={u.trading_mode} agent_mode={u.agent_mode}")
        print(f"  alloc_mode={u.live_alloc_mode} alloc_value={u.live_alloc_value}")

    # Check scheduler status via API
    print("\n=== SCHEDULER ===")
    from app.services.runtime_state import RuntimeStateService
    rs = RuntimeStateService()
    sched = rs.get_value(s, "scheduler_enabled")
    print(f"  scheduler_enabled={sched}")
