/**
 * Application-owned request decision made before transport.
 * @param {string} prompt
 * @returns {boolean}
 */
export function requestAccepted(prompt) {
  return prompt !== "";
}

/**
 * Application-owned response decision made after JSON decoding.
 * @param {boolean} accepted
 * @returns {boolean}
 */
export function responseAccepted(accepted) {
  return accepted;
}
