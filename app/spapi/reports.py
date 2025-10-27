
# Placeholder for real SP-API integration.
# For now we return small CSV strings to demonstrate the ETL/metrics flow.

def fetch_reports_stub():
    inventory_csv = """sku,qty,fc,at
SKU-AAA,120,FBA,2025-10-12T10:00:00Z
SKU-BBB,45,FBA,2025-10-12T10:00:00Z
SKU-CCC,0,FBA,2025-10-12T10:00:00Z
"""

    orders_csv = """sku,units,price,at
SKU-AAA,3,24.99,2025-10-12T12:00:00Z
SKU-BBB,1,39.00,2025-10-12T13:20:00Z
SKU-AAA,2,24.99,2025-10-12T15:00:00Z
"""

    settlement_csv = """sku,type,amount,at
SKU-AAA,FBA,7.12,2025-10-12T12:00:00Z
SKU-AAA,REFERRAL,3.75,2025-10-12T12:00:00Z
SKU-BBB,FBA,6.90,2025-10-12T13:20:00Z
SKU-BBB,REFERRAL,5.85,2025-10-12T13:20:00Z
"""

    return inventory_csv, orders_csv, settlement_csv
