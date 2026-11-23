package tailbridge

import (
	"encoding/json"
	"net"
	"net/netip"
	"os"
	"sync"
	"sync/atomic"

	"tailscale.com/net/netmon"
)

// AndroidNetworkSource supplies interface information through Android's connectivity API.
type AndroidNetworkSource interface {
	Snapshot() string
}

var androidNetwork struct {
	once   sync.Once
	source atomic.Pointer[AndroidNetworkSource]
}

// ConfigureAndroidNetwork must be called before starting the embedded node.
func ConfigureAndroidNetwork(source AndroidNetworkSource, cacheDir string) error {
	if err := os.MkdirAll(cacheDir, 0700); err != nil {
		return err
	}
	if err := os.Setenv("TS_LOGS_DIR", cacheDir); err != nil {
		return err
	}
	if err := os.Setenv("TMPDIR", cacheDir); err != nil {
		return err
	}
	androidNetwork.source.Store(&source)
	androidNetwork.once.Do(func() {
		netmon.RegisterInterfaceGetter(androidInterfaces)
	})
	return nil
}

func androidInterfaces() ([]netmon.Interface, error) {
	var snapshot struct {
		Default    string
		Interfaces []struct {
			Name      string
			Index     int
			MTU       int
			Addresses []string
		}
	}
	source := androidNetwork.source.Load()
	if source == nil || *source == nil {
		return nil, nil
	}
	if err := json.Unmarshal([]byte((*source).Snapshot()), &snapshot); err != nil {
		return nil, err
	}
	netmon.UpdateLastKnownDefaultRouteInterface(snapshot.Default)
	interfaces := make([]netmon.Interface, 0, len(snapshot.Interfaces))
	for _, entry := range snapshot.Interfaces {
		addresses := make([]net.Addr, 0, len(entry.Addresses))
		for _, value := range entry.Addresses {
			prefix, err := netip.ParsePrefix(value)
			if err != nil {
				continue
			}
			addresses = append(addresses, &net.IPNet{
				IP:   net.IP(prefix.Addr().AsSlice()),
				Mask: net.CIDRMask(prefix.Bits(), prefix.Addr().BitLen()),
			})
		}
		interfaces = append(interfaces, netmon.Interface{
			Interface: &net.Interface{
				Name: entry.Name, Index: entry.Index, MTU: entry.MTU,
				Flags: net.FlagUp | net.FlagRunning | net.FlagMulticast,
			},
			AltAddrs: addresses,
		})
	}
	return interfaces, nil
}
