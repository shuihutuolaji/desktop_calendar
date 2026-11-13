package com.wang.desktopcalendar.wecom

import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

/**
 * 企业微信推送：群机器人 Webhook + 自建应用两条通道，逻辑与桌面版一致。
 * 所有方法都是阻塞网络调用，必须在 IO 线程/协程里调用。
 */
object WeCom {

    private var cachedToken = ""
    private var tokenExpireAt = 0.0

    /** 企业微信 markdown 上限 4096 字节，按 UTF-8 字节安全截断 */
    private fun clipUtf8(text: String, limit: Int = 4000): String {
        val data = text.toByteArray(Charsets.UTF_8)
        return if (data.size <= limit) text
        else String(data, 0, limit, Charsets.UTF_8)
    }

    private fun postJson(url: String, payload: String): JSONObject {
        val conn = URL(url).openConnection() as HttpURLConnection
        conn.requestMethod = "POST"
        conn.connectTimeout = 10_000
        conn.readTimeout = 10_000
        conn.doOutput = true
        conn.setRequestProperty("Content-Type", "application/json")
        conn.outputStream.use { it.write(payload.toByteArray(Charsets.UTF_8)) }
        val body = conn.inputStream.use { it.readBytes().toString(Charsets.UTF_8) }
        return JSONObject(body)
    }

    private fun getJson(url: String): JSONObject {
        val conn = URL(url).openConnection() as HttpURLConnection
        conn.requestMethod = "GET"
        conn.connectTimeout = 10_000
        conn.readTimeout = 10_000
        val body = conn.inputStream.use { it.readBytes().toString(Charsets.UTF_8) }
        return JSONObject(body)
    }

    /** 群机器人 webhook 推送，返回 (是否成功, 错误信息) */
    fun push(webhook: String, content: String): Pair<Boolean, String> {
        if (webhook.isBlank()) return false to "Webhook 地址为空"
        return try {
            val payload = JSONObject()
                .put("msgtype", "markdown")
                .put("markdown", JSONObject().put("content", clipUtf8(content)))
                .toString()
            val data = postJson(webhook, payload)
            if (data.optInt("errcode", -1) == 0) true to ""
            else false to "errcode=${data.optInt("errcode")} ${data.optString("errmsg")}"
        } catch (e: Exception) {
            false to (e.message ?: e.toString())
        }
    }

    /** 自建应用推送（发到个人企业微信），返回 (是否成功, 错误信息) */
    fun appPush(corpId: String, agentId: String, secret: String, content: String,
                toUser: String = "@all"): Pair<Boolean, String> {
        if (corpId.isBlank() || agentId.isBlank() || secret.isBlank())
            return false to "应用参数不完整（CorpID / AgentID / Secret）"
        return try {
            var token = cachedToken
            val now = System.currentTimeMillis() / 1000.0
            if (token.isBlank() || now >= tokenExpireAt) {
                val tokenUrl = "https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid=" +
                    URLEncoder.encode(corpId, "UTF-8") +
                    "&corpsecret=" + URLEncoder.encode(secret, "UTF-8")
                val data = getJson(tokenUrl)
                if (data.optInt("errcode", 0) != 0) {
                    return false to "获取 access_token 失败：${data.optString("errmsg")}"
                }
                token = data.getString("access_token")
                cachedToken = token
                tokenExpireAt = now + data.optInt("expires_in", 7200) - 300
            }
            val payload = JSONObject()
                .put("touser", toUser.ifBlank { "@all" })
                .put("msgtype", "markdown")
                .put("agentid", agentId.toIntOrNull() ?: 0)
                .put("markdown", JSONObject().put("content", clipUtf8(content)))
                .toString()
            val data = postJson(
                "https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token=" +
                    URLEncoder.encode(token, "UTF-8"), payload)
            if (data.optInt("errcode", -1) == 0) true to ""
            else {
                cachedToken = "" // 失败清缓存，下次重取
                false to "errcode=${data.optInt("errcode")} ${data.optString("errmsg")}"
            }
        } catch (e: Exception) {
            false to (e.message ?: e.toString())
        }
    }
}
