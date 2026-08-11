package com.aihotradar.coreapi.subscription;

import jakarta.mail.MessagingException;
import jakarta.mail.internet.MimeMessage;
import java.nio.charset.StandardCharsets;
import java.util.function.Supplier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.mail.MailException;
import org.springframework.mail.javamail.JavaMailSender;
import org.springframework.mail.javamail.MimeMessageHelper;
import org.springframework.stereotype.Service;
import org.springframework.web.util.HtmlUtils;

@Service
public class SubscriptionMailer {
    private static final int MAX_ATTEMPTS = 3;

    private final JavaMailSender mailSender;
    private final String sender;
    private final String senderName;
    private final String publicBaseUrl;
    private final String smtpHost;

    public SubscriptionMailer(
            JavaMailSender mailSender,
            @Value("${ahr.email.from:}") String sender,
            @Value("${ahr.email.from-name:AI Hot Radar}") String senderName,
            @Value("${ahr.public-base-url:http://localhost:3000}") String publicBaseUrl,
            @Value("${spring.mail.host:}") String smtpHost) {
        this.mailSender = mailSender;
        this.sender = sender == null ? "" : sender.trim();
        this.senderName = senderName == null ? "AI Hot Radar" : senderName.trim();
        this.publicBaseUrl = stripTrailingSlash(publicBaseUrl);
        this.smtpHost = smtpHost == null ? "" : smtpHost.trim();
    }

    public void sendConfirmation(String recipient, String token) {
        ensureConfigured();
        String confirmUrl = publicBaseUrl + "/subscribe/confirm?token=" + token;
        sendWithRetries(
                () -> buildMessage(
                        recipient,
                        "确认订阅 AI Hot Radar 报告",
                        "请在 24 小时内打开以下地址并确认订阅：\n\n" + confirmUrl,
                        "<p>你正在订阅 AI Hot Radar 报告。</p>"
                                + "<p><a href=\"" + HtmlUtils.htmlEscape(confirmUrl) + "\">确认订阅</a></p>"
                                + "<p style=\"color:#6b6b66\">链接 24 小时内有效。若非本人操作，请忽略此邮件。</p>"));
    }

    public void sendReport(ReportEmailDeliveryService.DeliveryMessage delivery, String token) {
        ensureConfigured();
        String reportUrl = publicBaseUrl + "/reports/" + delivery.periodType() + "/" + delivery.periodKey();
        String unsubscribeUrl = publicBaseUrl + "/subscribe/unsubscribe?token=" + token;
        String plain = delivery.bodyMarkdown()
                + "\n\n在线阅读：" + reportUrl
                + "\n取消订阅：" + unsubscribeUrl;
        String summary = delivery.summary() == null ? "" : delivery.summary();
        String html = "<h1>" + HtmlUtils.htmlEscape(delivery.title()) + "</h1>"
                + (summary.isBlank() ? "" : "<p>" + HtmlUtils.htmlEscape(summary) + "</p>")
                + "<div style=\"white-space:pre-wrap;line-height:1.7\">"
                + HtmlUtils.htmlEscape(delivery.bodyMarkdown()) + "</div>"
                + "<p><a href=\"" + HtmlUtils.htmlEscape(reportUrl) + "\">在网站阅读并查看原始来源</a></p>"
                + "<hr><p style=\"font-size:12px;color:#6b6b66\">"
                + "内容由已发布报告渲染，事实请以原始来源为准。"
                + "<a href=\"" + HtmlUtils.htmlEscape(unsubscribeUrl) + "\">取消订阅</a></p>";
        try {
            mailSender.send(buildMessage(recipient(delivery), delivery.title(), plain, html));
        } catch (MailException exception) {
            throw new SubscriptionMailUnavailableException(exception);
        }
    }

    private String recipient(ReportEmailDeliveryService.DeliveryMessage delivery) {
        return delivery.recipient();
    }

    private MimeMessage buildMessage(String recipient, String subject, String plain, String html) {
        try {
            MimeMessage message = mailSender.createMimeMessage();
            MimeMessageHelper helper = new MimeMessageHelper(message, true, StandardCharsets.UTF_8.name());
            helper.setFrom(sender, senderName);
            helper.setTo(recipient);
            helper.setSubject(subject);
            helper.setText(plain, html);
            return message;
        } catch (MessagingException | java.io.UnsupportedEncodingException exception) {
            throw new SubscriptionMailUnavailableException(exception);
        }
    }

    private void sendWithRetries(Supplier<MimeMessage> messageFactory) {
        RuntimeException last = null;
        for (int attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
            try {
                mailSender.send(messageFactory.get());
                return;
            } catch (MailException | SubscriptionMailUnavailableException exception) {
                last = exception;
                if (attempt < MAX_ATTEMPTS) {
                    boundedBackoff(attempt);
                }
            }
        }
        throw new SubscriptionMailUnavailableException(last);
    }

    private void ensureConfigured() {
        if (smtpHost.isBlank() || sender.isBlank()) {
            throw new SubscriptionMailUnavailableException();
        }
    }

    private static void boundedBackoff(int attempt) {
        try {
            Thread.sleep(attempt == 1 ? 100L : 500L);
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            throw new SubscriptionMailUnavailableException(exception);
        }
    }

    private static String stripTrailingSlash(String value) {
        String result = value == null ? "" : value.trim();
        while (result.endsWith("/")) {
            result = result.substring(0, result.length() - 1);
        }
        return result;
    }
}
