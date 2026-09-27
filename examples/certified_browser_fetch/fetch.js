import { requestAccepted, responseAccepted } from "./browser.js";


/**
 * Real browser glue. Fetch, HTTP, JSON serialization, and Flask decoding are the explicitly
 * named external platform boundary in dag_contract.json; they are not presented as proved
 * JavaScript application logic.
 * @param {string} prompt
 * @returns {Promise<boolean>}
 */
export async function submitWithFetch(prompt) {
  const requestAcceptedValue = requestAccepted(prompt);
  const response = await fetch("/admit", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ requestAccepted: requestAcceptedValue }),
  });
  const payload = await response.json();
  return responseAccepted(payload.accepted);
}
