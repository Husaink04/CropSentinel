using System.Text.Json.Serialization;
using System.Text.Json;

namespace CropSentinel.AgentNative;

[JsonSerializable(typeof(MachineRegisterRequest))]
[JsonSerializable(typeof(RegistrationResponse))]
[JsonSerializable(typeof(HeartbeatRequest))]
[JsonSerializable(typeof(HeartbeatResponse))]
[JsonSerializable(typeof(JsonElement))]
[JsonSerializable(typeof(AppActivityRequest))]
[JsonSerializable(typeof(BrowserActivityRequest))]
[JsonSerializable(typeof(InputActivityRequest))]
[JsonSerializable(typeof(ScreenshotRequest))]
[JsonSerializable(typeof(FileActivityRequest))]
[JsonSerializable(typeof(NetworkActivityRequest))]
[JsonSerializable(typeof(PhishingCheckRequest))]
[JsonSerializable(typeof(PhishingCheckResponse))]
[JsonSerializable(typeof(PhishingEventRequest))]
[JsonSerializable(typeof(DlpEventRequest))]
[JsonSerializable(typeof(BatchActivityRequest))]
[JsonSerializable(typeof(BatchActivityResponse))]
[JsonSerializable(typeof(BackendErrorResponse))]
[JsonSerializable(typeof(WebRtcSessionDescriptionPayload))]
[JsonSerializable(typeof(WebRtcIceCandidatePayload))]
[JsonSerializable(typeof(WebRtcOfferSignal))]
[JsonSerializable(typeof(WebRtcIceSignal))]
[JsonSerializable(typeof(WebRtcEndSignal))]
[JsonSerializable(typeof(RemoteCommandResultSignal))]
internal sealed partial class AgentJsonSerializerContext : JsonSerializerContext
{
}
