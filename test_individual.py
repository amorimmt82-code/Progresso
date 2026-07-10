"""Find individual weighing records - try various approaches."""
import grpc
from grpc_reflection.v1alpha import reflection_pb2, reflection_pb2_grpc
from google.protobuf import descriptor_pb2 as dp2, empty_pb2
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
    "topcontrol.gamma.ps.core.warehouse.ContainerService",
    "topcontrol.gamma.ps.core.warehouse.GoodsReceiptService",
    "topcontrol.gamma.ps.core.orders.OrderService",
    "topcontrol.gamma.ps.core.traceability.TraceabilityService",
    "topcontrol.gamma.ps.core.analytics.ReportService",
]:
    add_sym(sym)

PRODUCTION_ID = "019bdadd-25a2-a3bb-a686-3ceb5594ebc1"

# ===== 1: ContainerService methods =====
print("=" * 60)
print("ContainerService:")
print("=" * 60)
try:
    sd = pool.FindServiceByName("topcontrol.gamma.ps.core.warehouse.ContainerService")
    for m in sd.methods:
        print(f"  {m.name}({m.input_type.name}) -> {m.output_type.name}")
except Exception as e:
    print(f"ERROR: {e}")

# ===== 2: GoodsReceiptService methods =====
print("\n" + "=" * 60)
print("GoodsReceiptService:")
print("=" * 60)
try:
    sd = pool.FindServiceByName("topcontrol.gamma.ps.core.warehouse.GoodsReceiptService")
    for m in sd.methods:
        print(f"  {m.name}({m.input_type.name}) -> {m.output_type.name}")
except Exception as e:
    print(f"ERROR: {e}")

# ===== 3: OrderService methods =====
print("\n" + "=" * 60)
print("OrderService:")
print("=" * 60)
try:
    sd = pool.FindServiceByName("topcontrol.gamma.ps.core.orders.OrderService")
    for m in sd.methods:
        print(f"  {m.name}({m.input_type.name}) -> {m.output_type.name}")
        # Print request fields for interesting methods
        if "Get" in m.name:
            for f in m.input_type.fields:
                tname = f.message_type.name if f.type == f.TYPE_MESSAGE else f.type
                if f.type == f.TYPE_ENUM:
                    vals = ", ".join([f"{v.name}={v.number}" for v in f.enum_type.values[:5]])
                    tname = f"{f.enum_type.name} [{vals}...]"
                print(f"    {f.name}: {tname}")
except Exception as e:
    print(f"ERROR: {e}")

# ===== 4: TraceabilityService with ORDER mode =====
print("\n" + "=" * 60)
print("TraceabilityService with TIME mode + filter differently")
print("=" * 60)

# Try with mode=1 (TIME) and time_filter=4 (TODAY) - but check why 403
# Actually let's check the full request schema
try:
    TReq = GetMessageClass(pool.FindMessageTypeByName("topcontrol.gamma.ps.core.traceability.GetTraceabilityDataRequest"))
    TResp = GetMessageClass(pool.FindMessageTypeByName("topcontrol.gamma.ps.core.traceability.GetTraceabilityDataResponse"))
    
    treq = TReq()
    treq.filter_mode = 1  # TIME
    treq.time_filter = 4  # TODAY
    treq.group_data_by_container = False
    
    tresp = channel.unary_unary(
        "/topcontrol.gamma.ps.core.traceability.TraceabilityService/GetTraceabilityData",
        request_serializer=TReq.SerializeToString,
        response_deserializer=TResp.FromString,
    )(treq, metadata=meta)
    
    items = list(tresp.items)
    print(f"Got {len(items)} traceability records")
    for i, item in enumerate(items[:3]):
        print(f"\n--- Record {i+1} ---")
        print(item)
        
except grpc.RpcError as e:
    print(f"FAILED: {e.code()} - {e.details()}")

# ===== 5: Try ContainerService to get containers for today =====
print("\n" + "=" * 60)
print("ContainerService.GetContainers")
print("=" * 60)
try:
    sd = pool.FindServiceByName("topcontrol.gamma.ps.core.warehouse.ContainerService")
    for m in sd.methods:
        if m.name == "GetContainers":
            print(f"GetContainers request schema:")
            for f in m.input_type.fields:
                if f.type == f.TYPE_MESSAGE:
                    print(f"  {f.name}: {f.message_type.name}")
                    for sf in f.message_type.fields:
                        tname = sf.message_type.name if sf.type == sf.TYPE_MESSAGE else sf.type
                        if sf.type == sf.TYPE_ENUM:
                            vals = ", ".join([f"{v.name}={v.number}" for v in sf.enum_type.values[:8]])
                            tname = f"{sf.enum_type.name} [{vals}...]"
                        print(f"    {sf.name}: {tname}")
                elif f.type == f.TYPE_ENUM:
                    vals = ", ".join([f"{v.name}={v.number}" for v in f.enum_type.values[:10]])
                    print(f"  {f.name}: {f.enum_type.name} [{vals}...]")
                else:
                    print(f"  {f.name}: type={f.type}")
            
            print(f"\nGetContainers response schema:")
            for f in m.output_type.fields:
                if f.type == f.TYPE_MESSAGE:
                    print(f"  {f.name}: {f.message_type.name}")
                    for sf in f.message_type.fields:
                        tname = sf.message_type.name if sf.type == sf.TYPE_MESSAGE else sf.type
                        label = "repeated " if sf.label == sf.LABEL_REPEATED else ""
                        print(f"    {label}{sf.name}: {tname}")
                else:
                    print(f"  {f.name}: type={f.type}")
except Exception as e:
    print(f"ERROR: {e}")

channel.close()
