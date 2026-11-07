from datetime import date

from sqlalchemy import select

from sherlock.models import AllocationRecord, Customer, Refund, RefundEntry, ReviewStatus


def test_tables_create_and_money_is_integer(session):
    session.add(Customer(customer_id="CUST-001", name="Acme"))
    refund = Refund(refund_id="R-1", importer="Importer", amount_cents=123_456, received_date=date(2025, 1, 1))
    refund.entries.append(RefundEntry(entry_number="E-1", amount_cents=123_456))
    session.add(refund)
    session.flush()
    session.add(
        AllocationRecord(
            refund_id="R-1",
            refund_entry_id=refund.entries[0].id,
            customer_id="CUST-001",
            amount_cents=123_456,
            confidence=0.9,
            review_status=ReviewStatus.AUTO_PROPOSED.value,
        )
    )
    session.commit()

    rec = session.execute(select(AllocationRecord)).scalar_one()
    assert isinstance(rec.amount_cents, int)
    assert rec.is_live
    assert rec.review_status == "auto_proposed"
