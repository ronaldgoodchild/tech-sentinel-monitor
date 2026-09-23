# Tech Sentinel Monitor — Probe IP Allow-Listing

## Overview

When monitoring external services, the probe worker's outbound IP must be allowed through customer firewalls. This guide covers configuring static egress IPs.

## Cloud NAT Configuration

### AWS (NAT Gateway)
1. Create Elastic IP for probe workers
2. Configure NAT Gateway in the probe worker's VPC subnet
3. Provide the Elastic IP to customers for allow-listing

```bash
# Get current egress IP
curl -s ifconfig.me
```

### GCP (Cloud NAT)
1. Reserve static IP: `gcloud compute addresses create ts-probe-ip --region=us-central1`
2. Create Cloud NAT with the static IP
3. Route probe worker traffic through Cloud NAT

### Azure (NAT Gateway)
1. Create Public IP: `az network public-ip create --name ts-probe-ip`
2. Create NAT Gateway and associate with probe worker subnet

## Customer Firewall Rules

Provide customers with:
- **Source IP(s)**: Your probe worker's static egress IP(s)
- **Ports**: Depends on monitor type (80/443 for HTTP, custom for TCP)
- **Protocol**: TCP for HTTP/TCP probes, ICMP for ping probes

### Sample firewall rule request template
```
Please allow the following for Tech Sentinel monitoring:
- Source IPs: x.x.x.x, y.y.y.y
- Destination: [customer endpoints]
- Ports: 443 (HTTPS), 5432 (PostgreSQL), ICMP (ping)
- Direction: Inbound
```

## IP Change Notification Process

1. **30-day notice**: Email customers before IP changes
2. **Dual-IP period**: Run both old and new IPs for 2 weeks
3. **Cutover**: Switch to new IP after confirmation
4. **Cleanup**: Remove old IP after 30 days

## Multiple Probe Locations

For geo-distributed monitoring, maintain a separate static IP per region and document all IPs in customer onboarding.
