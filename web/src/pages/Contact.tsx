import LegalLayout, { type LegalDoc } from "../components/LegalLayout";

const CONTACT_EMAIL = "panxinglong-1@126.com";

const doc: Record<"en" | "zh", LegalDoc> = {
  en: {
    title: "Contact us",
    intro: "Have a suggestion, question, or want to collaborate? Reach out any time.",
    sections: [
      {
        heading: "📧 Email",
        blocks: [
          { type: "p", text: "The most direct way to reach us." },
          { type: "p", text: CONTACT_EMAIL },
          { type: "p", text: "We usually reply within 1–3 business days." }
        ]
      },
      {
        heading: "🌐 Website",
        blocks: [
          { type: "p", text: "Learn more about ZhiMian’s features and how to use it." },
          { type: "p", text: "https://sleepai.chat" }
        ]
      },
      {
        heading: "📱 WeChat Mini Program",
        blocks: [
          { type: "p", text: "In mainland China, search “知眠” in WeChat to try the free Mini Program." }
        ]
      },
      {
        heading: "A note on use",
        blocks: [
          {
            type: "p",
            text: "ZhiMian’s AI assistant offers emotional support and sleep guidance and does not constitute professional medical diagnosis. If you have a serious sleep disorder or mental-health concern, please seek medical help. If you are in crisis in the US, call or text 988."
          }
        ]
      }
    ]
  },
  zh: {
    title: "联系我们",
    intro: "有建议、问题或想合作？随时联系我们。",
    sections: [
      {
        heading: "📧 邮件联系",
        blocks: [
          { type: "p", text: "最直接的联系我们方式。" },
          { type: "p", text: CONTACT_EMAIL },
          { type: "p", text: "我们通常在 1–3 个工作日内回复。" }
        ]
      },
      {
        heading: "🌐 官方网站",
        blocks: [
          { type: "p", text: "了解更多关于知眠的功能和使用方法。" },
          { type: "p", text: "https://sleepai.chat" }
        ]
      },
      {
        heading: "📱 微信小程序",
        blocks: [
          { type: "p", text: "在中国内地，于微信中搜索「知眠」即可找到我们的免费小程序。" }
        ]
      },
      {
        heading: "使用提醒",
        blocks: [
          {
            type: "p",
            text: "知眠 AI 助手提供情感支持和睡眠辅助，不构成专业医学诊断。如有严重睡眠障碍或心理健康问题，请及时就医；如处于危机中，请拨打当地心理援助热线。"
          }
        ]
      }
    ]
  }
};

export default function Contact() {
  return <LegalLayout doc={doc} />;
}
