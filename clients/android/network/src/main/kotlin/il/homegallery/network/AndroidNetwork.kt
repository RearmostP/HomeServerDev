package il.homegallery.network

import android.content.Context
import android.net.ConnectivityManager
import il.homegallery.nativebridge.tailbridge.AndroidNetworkSource
import java.net.NetworkInterface
import org.json.JSONArray
import org.json.JSONObject

internal class AndroidNetwork(context: Context) : AndroidNetworkSource {
    private val connectivity = requireNotNull(context.applicationContext.getSystemService(ConnectivityManager::class.java))

    override fun snapshot(): String {
        val active = connectivity.activeNetwork
        val default = active?.let(connectivity::getLinkProperties)?.interfaceName.orEmpty()
        val interfaces = JSONArray()
        val names = mutableSetOf<String>()
        for (network in listOfNotNull(active) + connectivity.allNetworks) {
            val properties = connectivity.getLinkProperties(network) ?: continue
            val name = properties.interfaceName ?: continue
            if (!names.add(name)) continue
            val addresses = JSONArray()
            for (link in properties.linkAddresses) {
                val host = link.address.hostAddress?.substringBefore('%') ?: continue
                addresses.put("$host/${link.prefixLength}")
            }
            interfaces.put(JSONObject().apply {
                put("name", name)
                put("index", runCatching { NetworkInterface.getByName(name)?.index }.getOrNull() ?: 0)
                put("mtu", properties.mtu)
                put("addresses", addresses)
            })
        }
        return JSONObject().put("default", default).put("interfaces", interfaces).toString()
    }
}
