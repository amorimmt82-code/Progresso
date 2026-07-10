"""Test WeighingReport with process_type_id and ExportService/TraceabilityService."""
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
    "topcontrol.gamma.ps.core.exporting.ExportService",
    "topcontrol.gamma.ps.core.traceability.TraceabilityService",
]:
    add_sym(sym)

# Process type IDs found from GetProcessTypes
PRODUCTION_ID = "019bdadd-25a2-a3bb-a686-3ceb5594ebc1"
HARVEST_ID = "019bdadd-27c4-4ab9-9260-f4d7bd78b7df"
FINAL_CHECK_ID = "019bdadd-2668-dbc4-924b-84ecdd852e35"

# ===== Test 1: WeighingReport with Production process_type_id =====
print("=" * 60)
print("TEST 1: GetWeighingReportDataAdHoc WITH process_type_id=Production")
print("=" * 60)

WReq = GetMessageClass(pool.FindMessageTypeByName("topcontrol.gamma.ps.core.analytics.GetWeighingReportDataAdHocRequest"))
WResp = GetMessageClass(pool.FindMessageTypeByName("topcontrol.gamma.ps.core.analytics.GetWeighingReportDataResponse"))

for pt_name, pt_id in [("Production", PRODUCTION_ID), ("Harvest", HARVEST_ID), ("FinalCheck", FINAL_CHECK_ID)]:
    wreq = WReq()
    wreq.time_filter = 3  # TODAY
    wreq.time_dimension = 1  # NONE
    wreq.dimensions.extend([3, 4, 1])  # USER, DEVICE, ARTICLE
    wreq.metrics.extend([1, 14, 17])  # QUANTITY, WEIGHT_KG, AVERAGE_WEIGHT_KG
    wreq.process_type_id.value = pt_id
    
    try:
        wresp = channel.unary_unary(
            "/topcontrol.gamma.ps.core.analytics.ReportService/GetWeighingReportDataAdHoc",
            request_serializer=WReq.SerializeToString,
            response_deserializer=WResp.FromString,
        )(wreq, metadata=meta)
        
        print(f"\n{pt_name}: Got {len(wresp.items)} items")
        for i, item in enumerate(wresp.items[:3]):
            user = item.user_display_name
            device = item.device_name
            article = item.article_name
            qty = item.quantity.value if item.HasField('quantity') else "N/A"
            wkg = item.weight_kg.value if item.HasField('weight_kg') else "N/A"
            avg = item.average_weight_kg.value if item.HasField('average_weight_kg') else "N/A"
            print(f"  [{i+1}] user={user}, device={device}, article={article}, qty={qty}, weight={wkg}, avg={avg}")
            
    except grpc.RpcError as e:
        print(f"\n{pt_name}: FAILED {e.code()} - {e.details()}")

# ===== Test 2: ExportService schema =====
print("\n" + "=" * 60)
print("TEST 2: ExportService methods")
print("=" * 60)

try:
    sd = pool.FindServiceByName("topcontrol.gamma.ps.core.exporting.ExportService")
    for m in sd.methods:
        print(f"\n  {m.name}({m.input_type.name}) -> {m.output_type.name}")
        print("  Request fields:")
        for f in m.input_type.fields:
            if f.type == f.TYPE_ENUM:
                vals = ", ".join([f"{v.name}={v.number}" for v in f.enum_type.values])
                print(f"    {f.name}: {f.enum_type.name} [{vals}]")
            elif f.type == f.TYPE_MESSAGE:
                print(f"    {f.name}: {f.message_type.name}")
            else:
                print(f"    {f.name}: type={f.type}")
except Exception as e:
    print(f"ERROR: {e}")

# ===== Test 3: TraceabilityService schema =====
print("\n" + "=" * 60) 
print("TEST 3: TraceabilityService methods")
print("=" * 60)

try:
    sd = pool.FindServiceByName("topcontrol.gamma.ps.core.traceability.TraceabilityService")
    for m in sd.methods:
        print(f"\n  {m.name}({m.input_type.name}) -> {m.output_type.name}")
        print("  Request fields:")
        for f in m.input_type.fields:
            if f.type == f.TYPE_ENUM:
                vals = ", ".join([f"{v.name}={v.number}" for v in f.enum_type.values])
                print(f"    {f.name}: {f.enum_type.name} [{vals}]")
            elif f.type == f.TYPE_MESSAGE:
                print(f"    {f.name}: {f.message_type.name}")
            else:
                print(f"    {f.name}: type={f.type}")
        print("  Response fields:")
        for f in m.output_type.fields:
            if f.type == f.TYPE_MESSAGE:
                print(f"    {f.name}: {f.message_type.name}")
                for sf in f.message_type.fields:
                    label = "repeated " if sf.label == sf.LABEL_REPEATED else ""
                    tname = sf.message_type.name if sf.type == sf.TYPE_MESSAGE else sf.type
                    print(f"      {label}{sf.name}: {tname}")
            else:
                print(f"    {f.name}: type={f.type}")
except Exception as e:
    print(f"ERROR: {e}")

# ===== Test 4: WeighingReport with HOUR time_dimension (gives per-entry data) =====
print("\n" + "=" * 60)
print("TEST 4: GetWeighingReportDataAdHoc HOUR dimension + Production")
print("=" * 60)

try:
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
    
    print(f"Got {len(wresp.items)} items")
    for i, item in enumerate(wresp.items[:10]):
        user = item.user_display_name
        device = item.device_name
        article = item.article_name
        qty = item.quantity.value if item.HasField('quantity') else "N/A"
        wkg = item.weight_kg.value if item.HasField('weight_kg') else "N/A"
        avg = item.average_weight_kg.value if item.HasField('average_weight_kg') else "N/A"
        t_from = f"{item.from_.hour:02d}:{item.from_.minute:02d}" if item.HasField("from_") else "?"
        t_to = f"{item.to.hour:02d}:{item.to.minute:02d}" if item.HasField("to") else "?"
        print(f"  [{i+1}] {t_from}-{t_to} user={user}, device={device}, article={article}, qty={qty}, weight={wkg}kg")
except grpc.RpcError as e:
    print(f"FAILED: {e.code()} - {e.details()}")

channel.close()
