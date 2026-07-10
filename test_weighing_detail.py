"""Get OrderWeighingDetail schema and actual individual weighing records."""
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

# First print OrderWeighingDetail schema
print("OrderWeighingDetail schema:")
try:
    detail_desc = pool.FindMessageTypeByName("topcontrol.gamma.ps.core.orders.OrderWeighingDetail")
    for f in detail_desc.fields:
        tname = f.message_type.name if f.type == f.TYPE_MESSAGE else f.type
        label = "repeated " if f.label == f.LABEL_REPEATED else ""
        print(f"  {label}{f.name}: {tname}")
except Exception as e:
    # Try to find it via the response
    resp_desc = pool.FindMessageTypeByName("topcontrol.gamma.ps.core.orders.GetOrderWeighingDetailsResponse")
    for f in resp_desc.fields:
        if f.name == "weighing_data":
            for sf in f.message_type.fields:
                if sf.name == "weighings":
                    print(f"  weighings item type: {sf.message_type.full_name}")
                    for wf in sf.message_type.fields:
                        tname = wf.message_type.name if wf.type == wf.TYPE_MESSAGE else wf.type
                        label = "repeated " if wf.label == wf.LABEL_REPEATED else ""
                        print(f"    {label}{wf.name}: {tname}")

# Active order IDs
ORDER_IDS = [
    "019d1a6f-07bd-b388-9bf5-8d520f978c59",  # Active: F2600068
    "019d1a6f-9dcf-81d6-b91f-6da99c02b0ad",  # Active: F2600069
    "019d19ba-c9bd-0405-8774-18f401d69ceb",  # Closed: F2600066
    "019d19bb-c564-9367-90ff-2e622ca4972d",  # Closed: F2600067
]

# Get weighing details for the first active order
Req = GetMessageClass(pool.FindMessageTypeByName("topcontrol.gamma.ps.core.orders.GetOrderWeighingDetailsRequest"))
Resp = GetMessageClass(pool.FindMessageTypeByName("topcontrol.gamma.ps.core.orders.GetOrderWeighingDetailsResponse"))

req = Req()
for oid in ORDER_IDS[2:3]:  # Closed order (likely smaller)
    uid = req.order_ids.add()
    uid.value = oid

try:
    resp = channel.unary_unary(
        "/topcontrol.gamma.ps.core.orders.OrderService/GetOrderWeighingDetails",
        request_serializer=Req.SerializeToString,
        response_deserializer=Resp.FromString,
    )(req, metadata=meta, timeout=60)
    
    weighings = list(resp.weighing_data.weighings)
    print(f"\nGot {len(weighings)} individual weighings for order {ORDER_IDS[0]}")
    
    # Print first 5 weighings
    for i, w in enumerate(weighings[:5]):
        print(f"\n--- Weighing {i+1} ---")
        # Print all non-empty fields  
        for f in w.DESCRIPTOR.fields:
            val = getattr(w, f.name)
            if val and str(val).strip():
                s = str(val).strip()
                if len(s) > 150:
                    s = s[:150] + "..."
                print(f"  {f.name}: {s}")
    
    # Also print lookup data summary
    print(f"\nLookup data:")
    for f in resp.lookup_data.DESCRIPTOR.fields:
        items = getattr(resp.lookup_data, f.name)
        print(f"  {f.name}: {len(items)} entries")

except grpc.RpcError as e:
    print(f"FAILED: {e.code()} - {e.details()}")

channel.close()
