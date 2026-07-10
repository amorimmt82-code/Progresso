"""Explore customer/business partner fields in gRPC WeighingReport response."""
import os
import grpc
from grpc_reflection.v1alpha import reflection_pb2, reflection_pb2_grpc
from google.protobuf import descriptor_pb2 as dp2
from google.protobuf.descriptor_pool import DescriptorPool
from google.protobuf.message_factory import GetMessageClass

GRPC_SERVER = "192.168.30.8:37270"
PRODUCTION_PROCESS_TYPE_ID = "019bdadd-25a2-a3bb-a686-3ceb5594ebc1"
TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".token")
token = open(TOKEN_FILE).read().strip() if os.path.exists(TOKEN_FILE) else None
EXCLUDED_USERS = {"MATHEUS"}

channel = grpc.insecure_channel(GRPC_SERVER)
pool = DescriptorPool()
stub = reflection_pb2_grpc.ServerReflectionStub(channel)
added = set()
meta = [("authorization", f"Bearer {token}")] if token else None

def add_file(fn):
    if fn in added:
        return
    req = reflection_pb2.ServerReflectionRequest(file_by_filename=fn)
    for r in stub.ServerReflectionInfo(iter([req]), metadata=meta):
        if r.HasField("file_descriptor_response"):
            for b in r.file_descriptor_response.file_descriptor_proto:
                fd = dp2.FileDescriptorProto()
                fd.ParseFromString(b)
                if fd.name not in added:
                    for dep in fd.dependency:
                        add_file(dep)
                    try:
                        pool.Add(fd)
                    except Exception:
                        pass
                    added.add(fd.name)

def add_sym(symbol):
    req = reflection_pb2.ServerReflectionRequest(file_containing_symbol=symbol)
    for r in stub.ServerReflectionInfo(iter([req]), metadata=meta):
        if r.HasField("file_descriptor_response"):
            for b in r.file_descriptor_response.file_descriptor_proto:
                fd = dp2.FileDescriptorProto()
                fd.ParseFromString(b)
                if fd.name not in added:
                    for dep in fd.dependency:
                        add_file(dep)
                    try:
                        pool.Add(fd)
                    except Exception:
                        pass
                    added.add(fd.name)

for sym in [
    "topcontrol.gamma.ps.core.statistics.StatisticService",
    "topcontrol.gamma.ps.core.analytics.ReportService",
    "topcontrol.gamma.ps.core.timetracking.TimeTrackingService",
]:
    add_sym(sym)

# 1) Explore WeighingReportDataItem all fields
print("=" * 80)
print("WeighingReportDataItem fields:")
print("=" * 80)
try:
    desc = pool.FindMessageTypeByName("topcontrol.gamma.ps.core.analytics.WeighingReportDataItem")
    for field in desc.fields:
        type_name = field.message_type.full_name if field.message_type else field.enum_type.full_name if field.enum_type else field.type
        print(f"  [{field.number}] {field.name}: {type_name}")
except Exception as e:
    print(f"  Error: {e}")

# 2) Explore WeighingReportDimension enum
print("\nWeighingReportDimension enum:")
try:
    enum_desc = pool.FindEnumTypeByName("topcontrol.gamma.ps.enums.WeighingReportDimension")
    for val in enum_desc.values:
        print(f"  {val.name} = {val.number}")
except Exception as e:
    print(f"  Error: {e}")

# 3) Explore WeighingStatisticDimension enum
print("\nWeighingStatisticDimension enum:")
try:
    enum_desc = pool.FindEnumTypeByName("topcontrol.gamma.ps.core.statistics.WeighingStatisticDimension")
    for val in enum_desc.values:
        print(f"  {val.name} = {val.number}")
except Exception as e:
    print(f"  Error: {e}")

# 4) Explore StatisticDataRecord fields
print("\nWeighingStatisticDataRecord fields:")
try:
    desc = pool.FindMessageTypeByName("topcontrol.gamma.ps.core.statistics.WeighingStatisticDataRecord")
    for field in desc.fields:
        type_name = field.message_type.full_name if field.message_type else field.enum_type.full_name if field.enum_type else field.type
        print(f"  [{field.number}] {field.name}: {type_name}")
except Exception as e:
    print(f"  Error: {e}")

# 5) Fetch data WITH CUSTOMER dimension
print("\n" + "=" * 80)
print("FETCHING DATA WITH CUSTOMER DIMENSION:")
print("=" * 80)

WRepReq = GetMessageClass(pool.FindMessageTypeByName(
    "topcontrol.gamma.ps.core.analytics.GetWeighingReportDataAdHocRequest"))
WRepResp = GetMessageClass(pool.FindMessageTypeByName(
    "topcontrol.gamma.ps.core.analytics.GetWeighingReportDataResponse"))

rreq = WRepReq()
rreq.time_filter = 3  # TODAY
rreq.time_dimension = 2  # HOUR
rreq.process_type_id.value = PRODUCTION_PROCESS_TYPE_ID
rreq.dimensions.extend([3, 4, 1, 6])  # USER, DEVICE, ARTICLE, CUSTOMER
rreq.metrics.extend([1, 14, 17])

report_resp = channel.unary_unary(
    "/topcontrol.gamma.ps.core.analytics.ReportService/GetWeighingReportDataAdHoc",
    request_serializer=WRepReq.SerializeToString,
    response_deserializer=WRepResp.FromString,
)(rreq, metadata=meta)

print(f"Total items: {len(report_resp.items)}")
customers_seen = set()
for item in report_resp.items[:10]:
    user = item.user_display_name
    article = item.article_name
    if user.upper() in EXCLUDED_USERS:
        continue
    # Print ALL fields with values
    for fd in item.DESCRIPTOR.fields:
        val = getattr(item, fd.name)
        if isinstance(val, str) and val:
            print(f"  {fd.name} = '{val}'")
        elif hasattr(val, 'value'):
            if val.value:
                print(f"  {fd.name}.value = '{val.value}'")
        elif hasattr(val, 'year') and val.year:
            print(f"  {fd.name} = {val.year}-{val.month:02d}-{val.day:02d} {val.hour:02d}:{val.minute:02d}")
    print("  ---")

# Check unique customers
for item in report_resp.items:
    if hasattr(item, 'customer_name') and item.customer_name:
        customers_seen.add(item.customer_name)
print(f"\nAll unique customers: {customers_seen}")

# 6) Statistics with CUSTOMER dim
print("\n" + "=" * 80)
print("STATISTICS WITH CUSTOMER DIMENSION (dim 4):")
print("=" * 80)

WStatReq = GetMessageClass(pool.FindMessageTypeByName(
    "topcontrol.gamma.ps.core.statistics.GetWeighingStatisticDataRequest"))
WStatResp = GetMessageClass(pool.FindMessageTypeByName(
    "topcontrol.gamma.ps.core.statistics.GetWeighingStatisticDataResponse"))

wreq = WStatReq()
wreq.time_dimension = 0
wreq.dimensions.extend([2, 3, 0, 4])  # USER, DEVICE, ARTICLE, dim4 (maybe customer)
wreq.metrics.extend([1, 14, 18])
fc = wreq.filter_configurations.add()
fc.time_filter.time_filter = 2  # TODAY

stat_resp = channel.unary_unary(
    "/topcontrol.gamma.ps.core.statistics.StatisticService/GetWeighingStatisticData",
    request_serializer=WStatReq.SerializeToString,
    response_deserializer=WStatResp.FromString,
)(wreq, metadata=meta)

print(f"Total records: {len(stat_resp.records)}")
for rec in stat_resp.records[:10]:
    user = rec.user.display_name if rec.HasField("user") else ""
    if user.upper() in EXCLUDED_USERS:
        continue
    # Print ALL fields
    for fd in rec.DESCRIPTOR.fields:
        val = getattr(rec, fd.name)
        if hasattr(val, 'display_name') and val.display_name:
            print(f"  {fd.name}.display_name = '{val.display_name}'")
        elif hasattr(val, 'name') and val.name:
            print(f"  {fd.name}.name = '{val.name}'")
        elif isinstance(val, str) and val:
            print(f"  {fd.name} = '{val}'")
    print("  ---")
