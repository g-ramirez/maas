# Copyright 2015-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""The VLAN handler for the WebSocket connection."""

__all__ = [
    "VLANHandler",
    ]

from maasserver.enum import (
    IPRANGE_TYPE,
    NODE_PERMISSION,
)
from maasserver.forms_iprange import IPRangeForm
from maasserver.models import (
    IPRange,
    RackController,
    Subnet,
    VLAN,
)
from maasserver.utils.orm import reload_object
from maasserver.websockets.handlers.timestampedmodel import (
    TimestampedModelHandler,
)
import netaddr
from provisioningserver.logger import get_maas_logger


maaslog = get_maas_logger("websockets.vlan")


class VLANHandler(TimestampedModelHandler):

    class Meta:
        queryset = (
            VLAN.objects.all()
                .select_related('primary_rack', 'secondary_rack')
                .prefetch_related("interface_set")
                .prefetch_related("subnet_set"))
        pk = 'id'
        allowed_methods = [
            'list',
            'get',
            'set_active',
            'configure_dhcp',
            'delete',
        ]
        listen_channels = [
            "vlan",
        ]

    def dehydrate(self, obj, data, for_list=False):
        # We need the system_id for each controller, since that's how we
        # need to look them up inside the Javascript controller.
        if obj.primary_rack is not None:
            data["primary_rack_sid"] = obj.primary_rack.system_id
        if obj.secondary_rack is not None:
            data["secondary_rack_sid"] = obj.secondary_rack.system_id
        data["subnet_ids"] = sorted([
            subnet.id
            for subnet in obj.subnet_set.all()
        ])
        node_ids = {
            interface.node_id
            for interface in obj.interface_set.all()
            if interface.node_id is not None
        }
        data["nodes_count"] = len(node_ids)
        if not for_list:
            data["node_ids"] = sorted(list(node_ids))
            data["space_ids"] = sorted(list({
                subnet.space_id
                for subnet in obj.subnet_set.all()
            }))
        return data

    def delete(self, parameters):
        """Delete this VLAN."""
        vlan = self.get_object(parameters)
        self.user = reload_object(self.user)
        assert self.user.has_perm(
            NODE_PERMISSION.ADMIN, vlan), "Permission denied."
        vlan.delete()

    def _configure_iprange_and_gateway(self, parameters):
        if 'subnet' in parameters and parameters['subnet'] is not None:
            subnet = Subnet.objects.get(id=parameters['subnet'])
        else:
            # Without a subnet, we cannot continue. (We need one to either
            # add an IP range, or specify a gateway IP.)
            return
        gateway = None
        if ('gateway' in parameters and
                parameters['gateway'] is not None):
            gateway_text = parameters['gateway'].strip()
            if len(gateway_text) > 0:
                gateway = netaddr.IPAddress(gateway_text)
                ipnetwork = netaddr.IPNetwork(subnet.cidr)
                if gateway not in ipnetwork:
                    raise ValueError(
                        "Gateway IP must be within specified subnet: %s" %
                        subnet.cidr)
        if ('start' in parameters and 'end' in parameters and
                parameters['start'] is not None and
                parameters['end'] is not None):
            start_text = parameters['start'].strip()
            end_text = parameters['end'].strip()
            # User wishes to add a range.
            if len(start_text) > 0 and len(end_text) > 0:
                start_ipaddr = netaddr.IPAddress(start_text)
                end_ipaddr = netaddr.IPAddress(end_text)
                if gateway is not None:
                    # If a gateway was specified, validate that it is not
                    # within the range the user wants to define.
                    desired_range = netaddr.IPRange(start_ipaddr, end_ipaddr)
                    if gateway in desired_range:
                        raise ValueError(
                            "Gateway IP must be outside the specified dynamic "
                            "range.")
                iprange_form = IPRangeForm(data={
                    "start_ip": str(start_ipaddr),
                    "end_ip": str(end_ipaddr),
                    "type": IPRANGE_TYPE.DYNAMIC,
                    "subnet": subnet.id,
                    "user": self.user.id,
                    "comment": "Added via 'Provide DHCP...' in Web UI."
                })
                iprange_form.save()
        if gateway is not None:
            subnet.gateway_ip = str(gateway)
            subnet.save()

    def configure_dhcp(self, parameters):
        """Helper method to look up rack controllers based on the parameters
        provided in the action input, and then reconfigure DHCP on the VLAN
        based on them.

        Requires a dictionary of parameters containing an ordered list of
        each desired rack controller system_id.

        If no controllers are specified, disables DHCP on the VLAN.
        """
        vlan = self.get_object(parameters)
        self.user = reload_object(self.user)
        assert self.user.has_perm(
            NODE_PERMISSION.ADMIN, vlan), "Permission denied."
        # Make sure the dictionary both exists, and has the expected number
        # of parameters, to prevent spurious log statements.
        if 'extra' in parameters:
            self._configure_iprange_and_gateway(parameters['extra'])
        iprange_count = IPRange.objects.filter(
            type=IPRANGE_TYPE.DYNAMIC, subnet__vlan=vlan).count()
        if iprange_count == 0:
            raise ValueError(
                "Cannot configure DHCP: At least one dynamic range is "
                "required.")
        controllers = [
            RackController.objects.get(system_id=system_id)
            for system_id in parameters['controllers']
        ]
        vlan.configure_dhcp(controllers)
        vlan.save()
