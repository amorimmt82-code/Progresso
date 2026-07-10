"""Test TraceabilityService and WeighingReport HOUR for individual records."""
import grpc
from grpc_reflection.v1alpha import reflection_pb2, reflection_pb2_grpc
from google.protobuf import descriptor_pb2 as dp2
from google.protobuf.descriptor_pool import DescriptorPool
from google.protobuf.message_factory import GetMessageClass

GRPC_SERVER = "192.168.30.8:37270"
token = open(".token").read().strip()
meta = [("authorization", f"Bearer {token}")]

channel = grpc.insecure_channel(GRPC_SERVER)
stub = reflection_pb2_grpc.ServerReflectionStub(channel)

pool = DescriptorPool()
added = set()

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
                    except:
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
                    except:
                        pass
                    added.add(fd.name)

for sym in [
    "topcontrol.gamma.ps.core.analytics.ReportService",
    "topcontrol.gamma.ps.core.traceability.TraceabilityService",
]:
    add_sym(sym)

PRODUCTION_ID = "019bdadd-25a2-a3bb-a686-3ceb5594ebc1"

# ===== Test 1: TraceabilityService =====
print("=" * 60)
print("TEST 1: TraceabilityService.GetTraceabilityData (TODAY)")
print("=" * 60)

try:
    TReq = GetMessageClass(pool.FindMessageTypeByName("topcontrol.gamma.ps.core.traceability.GetTraceabilityDataRequest"))
    TResp = GetMessageClass(pool.FindMessageTypeByName("topcontrol.gamma.ps.core.traceability.GetTraceabilityDataResponse"))
    
    treq = TReq()
    treq.filter_mode = 1  # TIME
    treq.time_filter = 4  # TODAY
    
    tresp = channel.unary_unary(
        "/topcontrol.gamma.ps.core.traceability.TraceabilityService/GetTraceabilityData",
        request_serializer=TReq.SerializeToString,
        response_deserializer=TResp.FromString,
    )(treq, metadata=meta)
    
    items = list(tresp.items)
    print(f"Got {len(items)} traceability records")
    for i, item in enumerate(items[:5]):
        print(f"\n--- Record {i+1} ---")
        print(item)
        
except grpc.RpcError as e:
    print(f"FAILED: {e.code()} - {e.details()}")

# ===== Test 2: WeighingReport HOUR with 'from' field =====
print("\n" + "=" * 60)
print("TEST 2: GetWeighingReportDataAdHoc HOUR (first 10)")
print("=" * 60)

try:
    WReq = GetMessageClass(pool.FindMessageTypeByName("topcontrol.gamma.ps.core.analytics.GetWeighingReportDataAdHocRequest"))
    WResp = GetMessageClass(pool.FindMessageTypeByName("topcontrol.gamma.ps.core.analytics.GetWeighingReportDataResponse"))
    
    # Check actual field names
    resp_desc = pool.FindMessageTypeByName("topcontrol.gamma.ps.core.analytics.GetWeighingReportDataResponseItem")
    time_fields = [f.name for f in resp_desc.fields if "from" in f.name.lower() or "to" in f.name.lower() or "time" in f.name.lower()]
    print(f"Time-related fields: {time_fields}")
    all_fields = [f.name for f in resp_desc.fields]
    print(f"First 20 fields: {all_fields[:20]}")
    
    wreq = WReq()
    wreq.time_filter = 3  # TODAY
    wreq.time_dimension = 2  # HOUR
    wreq.process_type_id.value = PRODUCTION_ID
    wreq.dimensions.extend([3, 4, 1])  # USER, DEVICE, ARTICLE
    wreq.metrics.extend([1, 14, 17])  # QUANTITY, WEIGHT_KG, AVERAGE_WEIGHT_KG
    
    wresp = channel.unary_unary(
        "/topcontrol.gamma.ps.core.analytics.ReportService/GetWeighingReportDataAdHoc",
        request_serializer=WReq.SerializeToString,
        response_deserializer=WResp.FromString,
    )(wreq, metadata=meta)
    
    print(f"\nGot {len(wresp.items)} items")
    for i, item in enumerate(wresp.items[:10]):
        user = item.user_display_name
        device = item.device_name
        article = item.article_name
        qty = item.quantity.value if item.HasField('quantity') else "N/A"
        wkg = item.weight_kg.value if item.HasField('weight_kg') else "N/A"
        
        # Try both 'from' and 'from_' 
        try:
            ft = getattr(item, 'from')
            t_from = f"{ft.day:02d}/{ft.month:02d} {ft.hour:02d}:{ft.minute:02d}"
        except:
            try:
                # protobuf uses 'from_' since 'from' is Python keyword  
                # But in descriptor it might just be field number 1
                desc = item.DESCRIPTOR
                f_field = desc.fields_by_number[1]
                ft = getattr(item, f_field.name)
                t_from = f"{ft.day:02d}/{ft.month:02d} {ft.hour:02d}:{ft.minute:02d}"
            except:
                t_from = "?"
        
        try:
            tt = item.to
            t_to = f"{tt.day:02d}/{tt.month:02d} {tt.hour:02d}:{tt.minute:02d}"
        except:
            t_to = "?"
        
        print(f"  [{i+1}] {t_from}-{t_to} {user} | {device} | {article} | qty={qty} wkg={wkg}")
        
except grpc.RpcError as e:
    print(f"FAILED: {e.code()} - {e.details()}")

channel.close()
