package tailbridge

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/cookiejar"
	"net/url"
	"os"
	"regexp"
	"strings"
	"time"

	"tailscale.com/client/local"
	"tailscale.com/tsnet"
)

const maxBody = 26 << 20

var sessionToken = regexp.MustCompile(`^[a-zA-Z0-9_-]{43}$`)

var galleryPath = regexp.MustCompile(`^/api/[a-zA-Z0-9_/-]+$`)

type Client struct {
	server  *tsnet.Server
	local   *local.Client
	http    *http.Client
	origin  string
	tailnet string
}

type nodeStatus struct {
	State   string `json:"state"`
	AuthURL string `json:"authUrl,omitempty"`
}

type reply struct {
	Status int    `json:"status"`
	Body   string `json:"body"`
}

func Start(stateDir, hostname, serverHost string) (*Client, error) {
	galleryHost, err := url.Parse("https://" + serverHost)
	if err != nil || galleryHost.Host != serverHost || galleryHost.Hostname() != serverHost ||
		galleryHost.Path != "" || galleryHost.RawQuery != "" || galleryHost.Fragment != "" ||
		!strings.HasSuffix(serverHost, ".ts.net") {
		return nil, errors.New("invalid gallery host")
	}
	_, tailnet, valid := strings.Cut(serverHost, ".")
	if !valid {
		return nil, errors.New("invalid gallery host")
	}
	if err := os.MkdirAll(stateDir, 0700); err != nil {
		return nil, err
	}
	server := &tsnet.Server{
		Dir: stateDir, Hostname: hostname,
		UserLogf: func(string, ...any) {},
		Logf:     func(string, ...any) {},
	}
	localClient, err := server.LocalClient()
	if err != nil {
		return nil, err
	}
	jar, err := cookiejar.New(nil)
	if err != nil {
		_ = server.Close()
		return nil, err
	}
	httpClient := server.HTTPClient()
	httpClient.Jar = jar
	httpClient.Timeout = 90 * time.Second
	httpClient.CheckRedirect = func(*http.Request, []*http.Request) error {
		return http.ErrUseLastResponse
	}
	return &Client{server: server, local: localClient, http: httpClient, origin: galleryHost.String(), tailnet: tailnet}, nil
}

func (c *Client) Status() (string, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	status, err := c.local.StatusWithoutPeers(ctx)
	if err != nil {
		return "", err
	}
	state := status.BackendState
	if state == "Running" && (status.CurrentTailnet == nil ||
		!strings.EqualFold(strings.TrimSuffix(status.CurrentTailnet.MagicDNSSuffix, "."), c.tailnet)) {
		state = "WrongTailnet"
	}
	value, err := json.Marshal(nodeStatus{State: state, AuthURL: status.AuthURL})
	return string(value), err
}

func (c *Client) Probe() error {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, c.origin+"/", nil)
	if err != nil {
		return err
	}
	response, err := c.http.Do(request)
	if err != nil {
		return err
	}
	defer response.Body.Close()
	page, err := io.ReadAll(io.LimitReader(response.Body, 32<<10))
	if err != nil || response.StatusCode != http.StatusOK || !bytes.Contains(page, []byte("toggle-auth")) {
		return errors.New("gallery is unavailable")
	}
	return nil
}

func (c *Client) Request(method, path, contentType, body string) (string, error) {
	if !galleryPath.MatchString(path) || strings.Contains(path, "//") {
		return "", errors.New("invalid gallery endpoint")
	}
	if method != http.MethodGet && method != http.MethodPost {
		return "", errors.New("invalid HTTP method")
	}
	if len(body) > base64.StdEncoding.EncodedLen(maxBody) {
		return "", errors.New("request too large")
	}
	payload, err := base64.StdEncoding.DecodeString(body)
	if err != nil || len(payload) > maxBody || (method == http.MethodGet && len(payload) != 0) {
		return "", errors.New("invalid request body")
	}
	request, err := http.NewRequest(method, c.origin+path, bytes.NewReader(payload))
	if err != nil {
		return "", err
	}
	if method == http.MethodPost {
		request.Header.Set("Origin", c.origin)
		request.Header.Set("Content-Type", contentType)
	}
	response, err := c.http.Do(request)
	if err != nil {
		return "", err
	}
	defer response.Body.Close()
	data, err := io.ReadAll(io.LimitReader(response.Body, maxBody+1))
	if err != nil || len(data) > maxBody {
		return "", errors.New("invalid response body")
	}
	value, err := json.Marshal(reply{Status: response.StatusCode, Body: base64.StdEncoding.EncodeToString(data)})
	return string(value), err
}

// SessionToken returns the current gallery authentication cookie.
func (c *Client) SessionToken() string {
	for _, cookie := range c.http.Jar.Cookies(c.galleryURL()) {
		if cookie.Name == "gallery_session" {
			return cookie.Value
		}
	}
	return ""
}

// RestoreSession restores a previously authenticated gallery cookie from app storage.
func (c *Client) RestoreSession(token string) bool {
	if !sessionToken.MatchString(token) {
		return false
	}
	c.http.Jar.SetCookies(c.galleryURL(), []*http.Cookie{
		{Name: "gallery_session", Value: token, Path: "/", Secure: true, HttpOnly: true},
	})
	return true
}

func (c *Client) galleryURL() *url.URL {
	return &url.URL{Scheme: "https", Host: strings.TrimPrefix(c.origin, "https://"), Path: "/"}
}

func (c *Client) Close() error {
	c.http.CloseIdleConnections()
	return c.server.Close()
}
