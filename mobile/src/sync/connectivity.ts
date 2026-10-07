export interface NetworkHint {
  isConnected?: boolean;
  isInternetReachable?: boolean;
}

export function canAttemptBackendSync(network: NetworkHint): boolean {
  // Android's public-internet validation is not reachability to our Django
  // deployment: a connected LAN/VPN can reach it without that validation.
  // Only a known disconnected device is skipped. The existing bounded,
  // redirect-refusing backend request and server authorization stay decisive.
  return network.isConnected !== false;
}
