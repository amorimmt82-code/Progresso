"""Test TimeTrackingService.GetLogins and find process_type_id for WeighingReport."""
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

# Load needed services
for sym in [
    "topcontrol.gamma.ps.core.timetracking.TimeTrackingService",
    "topcontrol.gamma.ps.core.analytics.ReportService",
    "topcontrol.gamma.ps.core.processing.ProcessService",
    "topcontrol.gamma.ps.core.statistics.StatisticService",
]:
    add_sym(sym)

# ===== Test 1: GetLogins (individual login records with timestamps) =====
print("=" * 60)
print("TEST 1: TimeTrackingService.GetLogins (TODAY)")
print("=" * 60)

try:
    Req = GetMessageClass(pool.FindMessageTypeByName("topcontrol.gamma.ps.core.timetracking.GetLoginsRequest"))
    Resp = GetMessageClass(pool.FindMessageTypeByName("topcontrol.gamma.ps.core.timetracking.GetLoginsResponse"))
    
    req = Req()
    req.time_filter = 3  # TODAY
    
    resp = channel.unary_unary(
        "/topcontrol.gamma.ps.core.timetracking.TimeTrackingService/GetLogins",
        request_serializer=Req.SerializeToString,
        response_deserializer=Resp.FromString,
    )(req, metadata=meta)
    
    # Print response schema first
    resp_desc = pool.FindMessageTypeByName("topcontrol.gamma.ps.core.timetracking.GetLoginsResponse")
    print("Response message fields:")
    for f in resp_desc.fields:
        print(f"  {f.name} ({f.type})")
        if f.type == f.TYPE_MESSAGE:
            for sf in f.message_type.fields:
                print(f"    {sf.name} ({sf.type})")
                if sf.type == sf.TYPE_MESSAGE and sf.message_type.name not in ("Uuid",):
                    for ssf in sf.message_type.fields:
                        print(f"      {ssf.name}")
    
    # List all fields dynamically
    fields = [f.name for f in resp_desc.fields]
    print(f"\nTop-level fields: {fields}")
    
    # Access first repeated field
    main_field = fields[0] if fields else None
    if main_field:
        items = getattr(resp, main_field)
        print(f"Got {len(items)} items via '{main_field}'")
        for i, item in enumerate(list(items)[:5]):
            print(f"\n--- Item {i+1} ---")
            print(item)
        
except grpc.RpcError as e:
    print(f"FAILED: {e.code()} - {e.details()}")

# ===== Test 2: ProcessService.GetProcessTypes to find process_type_id =====
print("\n" + "=" * 60)
print("TEST 2: ProcessService.GetProcessTypes")
print("=" * 60)

try:
    from google.protobuf import empty_pb2
    Resp2 = GetMessageClass(pool.FindMessageTypeByName("topcontrol.gamma.ps.core.processing.GetProcessTypesResponse"))
    
    resp2 = channel.unary_unary(
        "/topcontrol.gamma.ps.core.processing.ProcessService/GetProcessTypes",
        request_serializer=empty_pb2.Empty.SerializeToString,
        response_deserializer=Resp2.FromString,
    )(empty_pb2.Empty(), metadata=meta)
    
    print(f"Response: {resp2}")
    
except grpc.RpcError as e:
    print(f"FAILED: {e.code()} - {e.details()}")

# ===== Test 3: ReportService.GetWeighingReportDataAdHoc without process_type_id =====
print("\n" + "=" * 60)
print("TEST 3: GetWeighingReportDataAdHoc (TODAY, no process_type_id)")
print("=" * 60)

try:
    WReq = GetMessageClass(pool.FindMessageTypeByName("topcontrol.gamma.ps.core.analytics.GetWeighingReportDataAdHocRequest"))
    WResp = GetMessageClass(pool.FindMessageTypeByName("topcontrol.gamma.ps.core.analytics.GetWeighingReportDataResponse"))
    
    wreq = WReq()
    wreq.time_filter = 3  # TODAY
    wreq.time_dimension = 1  # NONE
    wreq.dimensions.extend([3, 4, 1])  # USER, DEVICE, ARTICLE
    wreq.metrics.extend([1, 14, 17])  # QUANTITY, WEIGHT_KG, AVERAGE_WEIGHT_KG
    
    wresp = channel.unary_unary(
        "/topcontrol.gamma.ps.core.analytics.ReportService/GetWeighingReportDataAdHoc",
        request_serializer=WReq.SerializeToString,
        response_deserializer=WResp.FromString,
    )(wreq, metadata=meta)
    
    print(f"Got {len(wresp.items)} items")
    for i, item in enumerate(wresp.items[:3]):
        print(f"\n--- Item {i+1} ---")
        print(f"  user: {item.user_display_name}")
        print(f"  device: {item.device_name}")
        print(f"  article: {item.article_name}")
        print(f"  quantity: {item.quantity.value if item.HasField('quantity') else 'N/A'}")
        print(f"  weight_kg: {item.weight_kg.value if item.HasField('weight_kg') else 'N/A'}")
        print(f"  from: {item.from_.year}/{item.from_.month}/{item.from_.day} {item.from_.hour}:{item.from_.minute}:{item.from_.second}" if item.HasField("from_") else "  from: N/A")
        print(f"  to: {item.to.year}/{item.to.month}/{item.to.day} {item.to.hour}:{item.to.minute}:{item.to.second}" if item.HasField("to") else "  to: N/A")
    
except grpc.RpcError as e:
    print(f"FAILED: {e.code()} - {e.details()}")

# ===== Test 4: StatisticService.GetWeighingStatisticData with TIME dimension =====
print("\n" + "=" * 60)
print("TEST 4: StatisticService.GetWeighingStatisticData with HOUR time_dimension")
print("=" * 60)

try:
    SReq = GetMessageClass(pool.FindMessageTypeByName("topcontrol.gamma.ps.core.statistics.GetWeighingStatisticDataRequest"))
    SResp = GetMessageClass(pool.FindMessageTypeByName("topcontrol.gamma.ps.core.statistics.GetWeighingStatisticDataResponse"))
    
    sreq = SReq()
    sreq.time_dimension = 2  # Try HOUR or more granular
    sreq.dimensions.extend([2, 3, 0])  # USER, DEVICE, ARTICLE
    sreq.metrics.extend([1, 14, 18])  # QUANTITY_SUM, WEIGHT_KG, AVG_WEIGHT_KG
    fc = sreq.filter_configurations.add()
    fc.time_filter.time_filter = 2  # TODAY
    
    sresp = channel.unary_unary(
        "/topcontrol.gamma.ps.core.statistics.StatisticService/GetWeighingStatisticData",
        request_serializer=SReq.SerializeToString,
        response_deserializer=SResp.FromString,
    )(sreq, metadata=meta)
    
    print(f"Got {len(sresp.records)} records")
    
    # Check what time-related fields are in records
    rec_desc = pool.FindMessageTypeByName("topcontrol.gamma.ps.core.statistics.WeighingStatisticRecord")
    print("\nRecord fields:")
    for f in rec_desc.fields:
        print(f"  {f.name} ({f.message_type.name if f.type == f.TYPE_MESSAGE else f.type})")
    
    for i, rec in enumerate(sresp.records[:5]):
        print(f"\n--- Record {i+1} ---")
        user = rec.user.display_name if rec.HasField("user") else ""
        device = rec.device.name if rec.HasField("device") else ""
        article = rec.article.name if rec.HasField("article") else ""
        weight = float(rec.totals.weight_kg.value) if rec.totals.HasField("weight_kg") else 0
        qty = float(rec.totals.quantity_sum.value) if rec.totals.HasField("quantity_sum") else 0
        
        # Check time fields
        time_info = ""
        if rec.HasField("time"):
            t = rec.time
            time_info = str(t)
        
        print(f"  user={user}, device={device}, article={article}")
        print(f"  weight={weight}, qty={qty}")
        print(f"  time={time_info}")
        
except grpc.RpcError as e:
    print(f"FAILED: {e.code()} - {e.details()}")

channel.close()
