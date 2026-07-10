"""Test GetOrderOverviewData and try GetOrderWeighingDetails with long timeout."""
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

add_sym("topcontrol.gamma.ps.core.orders.OrderService")

# Test 1: GetOrderOverviewData schema + data
print("=" * 60)
print("GetOrderOverviewData response schema:")
print("=" * 60)
resp_desc = pool.FindMessageTypeByName("topcontrol.gamma.ps.core.orders.GetOrderOverviewDataResponse")
for f in resp_desc.fields:
    tname = f.message_type.name if f.type == f.TYPE_MESSAGE else f.type
    label = "repeated " if f.label == f.LABEL_REPEATED else ""
    print(f"  {label}{f.name}: {tname}")
    if f.type == f.TYPE_MESSAGE:
        for sf in f.message_type.fields:
            tname2 = sf.message_type.name if sf.type == sf.TYPE_MESSAGE else sf.type
            label2 = "repeated " if sf.label == sf.LABEL_REPEATED else ""
            print(f"    {label2}{sf.name}: {tname2}")
            if sf.type == sf.TYPE_MESSAGE and sf.message_type.name not in ("Uuid", "Decimal", "LocalDateTime", "LocalDate", "Int32Value", "Int64Value", "Duration", "MultilingualString"):
                for ssf in sf.message_type.fields:
                    tname3 = ssf.message_type.name if ssf.type == ssf.TYPE_MESSAGE else ssf.type
                    print(f"      {ssf.name}: {tname3}")

Req = GetMessageClass(pool.FindMessageTypeByName("topcontrol.gamma.ps.core.orders.GetOrderOverviewDataRequest"))
Resp = GetMessageClass(pool.FindMessageTypeByName("topcontrol.gamma.ps.core.orders.GetOrderOverviewDataResponse"))

req = Req()
req.time_filter = 0  # TODAY_ALL

try:
    resp = channel.unary_unary(
        "/topcontrol.gamma.ps.core.orders.OrderService/GetOrderOverviewData",
        request_serializer=Req.SerializeToString,
        response_deserializer=Resp.FromString,
    )(req, metadata=meta, timeout=30)
    
    fields = [f.name for f in resp.DESCRIPTOR.fields]
    for fn in fields:
        items = getattr(resp, fn)
        if hasattr(items, '__len__'):
            print(f"\n{fn}: {len(items)} items")
            if len(items) > 0:
                first = list(items)[0]
                for ff in first.DESCRIPTOR.fields:
                    val = getattr(first, ff.name)
                    if val and str(val).strip():
                        s = str(val).strip()
                        if len(s) > 100:
                            s = s[:100] + "..."
                        print(f"  {ff.name}: {s}")
        else:
            print(f"\n{fn}: {items}")
            
except grpc.RpcError as e:
    print(f"FAILED: {e.code()} - {e.details()}")

# Test 2: Try GetOrderWeighingDetails with the smallest order (69: target 500k) and longer timeout
print("\n" + "=" * 60)
print("GetOrderWeighingDetails for smallest order (F2600069, 120s timeout)")
print("=" * 60)

Req2 = GetMessageClass(pool.FindMessageTypeByName("topcontrol.gamma.ps.core.orders.GetOrderWeighingDetailsRequest"))
Resp2 = GetMessageClass(pool.FindMessageTypeByName("topcontrol.gamma.ps.core.orders.GetOrderWeighingDetailsResponse"))

req2 = Req2()
uid = req2.order_ids.add()
uid.value = "019d1a6f-9dcf-81d6-b91f-6da99c02b0ad"  # F2600069 (500k target)

try:
    resp2 = channel.unary_unary(
        "/topcontrol.gamma.ps.core.orders.OrderService/GetOrderWeighingDetails",
        request_serializer=Req2.SerializeToString,
        response_deserializer=Resp2.FromString,
    )(req2, metadata=meta, timeout=120)
    
    weighings = list(resp2.weighing_data.weighings)
    print(f"Got {len(weighings)} individual weighings!")
    
    # Build user lookup
    user_lookup = {}
    for entry in resp2.lookup_data.users:
        user_lookup[entry.key] = entry.value
    
    # Build device lookup 
    device_lookup = {}
    for entry in resp2.lookup_data.devices:
        device_lookup[entry.key] = entry.value
    
    # Print first 10 weighings with resolved names
    for i, w in enumerate(weighings[:10]):
        reg = w.registered_at
        reg_str = f"{reg.day:02d}/{reg.month:02d}/{reg.year} {reg.hour:02d}:{reg.minute:02d}:{reg.second:02d}"
        net = w.net_weight_kg.value if w.HasField("net_weight_kg") else "?"
        
        # Resolve user_ids
        users = []
        for uid in w.user_ids:
            if uid.value in user_lookup:
                u = user_lookup[uid.value]
                users.append(u.display_name if hasattr(u, 'display_name') else str(u))
            else:
                users.append(uid.value[:8])
        user_str = ", ".join(users) if users else "?"
        
        # Resolve device
        dev_id = w.device_id.value if w.HasField("device_id") else ""
        if dev_id in device_lookup:
            d = device_lookup[dev_id]
            dev_str = d.name if hasattr(d, 'name') else str(d)
        else:
            dev_str = dev_id[:8] if dev_id else "?"
        
        print(f"  [{i+1}] {reg_str} | {user_str} | {dev_str} | {net}kg")

except grpc.RpcError as e:
    print(f"FAILED: {e.code()} - {e.details()}")

channel.close()
